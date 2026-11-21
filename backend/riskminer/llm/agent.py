"""Zapytaj as an agent: the model plans, calls tools in several steps, then answers (user request, 21.11.2026).

Each step is one gateway call (prompt `agent`, structured output AgentStep), so routing, budget, llm_call logging and
replay in tests work as for every other task. Tools are read-only:
  opis_aplikacji  what each screen does and how to use it ("co mogę tu zrobić?"), from APP_GUIDE
  dane            numbers from the case base: the curated intents first, else NL->SQL (llm/tasks/nl2sql), with n
  dokumenty       full-text search in public documents (chunks)
  projekt         one of the 22 pilot projects
  monitoring      late share by voivodeship and signal count (monitoring service), per sector
The response carries the visible steps (thought, tool call, short result) and a final Answer-shaped dict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.llm import gateway
from riskminer.llm.backends.base import Text

MAX_TOOL_CALLS = 4
Action = Literal["opis_aplikacji", "dane", "dokumenty", "projekt", "monitoring", "final"]
TOOL_LABEL = {"opis_aplikacji": "opis aplikacji", "dane": "dane z bazy umów", "dokumenty": "wyszukiwanie w dokumentach",
              "projekt": "projekt pilotażowy", "monitoring": "monitoring"}


class AgentStep(BaseModel):
    thought: str = Field(description="1-2 zdania po polsku: co teraz robisz")
    action: Action
    action_input: str = ""
    final_answer: str | None = None


APP_GUIDE: dict[str, str] = {
    "/": ("Pulpit (po zalogowaniu): podsumowanie bazy (ile umów skończyło się po terminie), kafle: sprawy czekające na "
          "przegląd, nowe sygnały w monitoringu, Twoje analizy; okno Zapytaj pamięć; źródła danych z datą pobrania."),
    "/monitoring": ("Monitoring: mapa i lista województw, powiatów i gmin z odsetkiem umów zakończonych po terminie, "
                    "średnim opóźnieniem i dopłatami. Przełącz Zakończone / W toku, filtruj podsektorem, wartością i "
                    "latami, wyszukaj gminę, zamawiającego, wykonawcę albo numer BZP. Kliknij region, żeby zejść niżej; "
                    "sygnały to umowy po planowanym terminie bez ogłoszenia o wykonaniu. Z umowy przejdziesz do karty, "
                    "a ekspert może ją obserwować albo zgłosić jako przypadek do przeglądu. Suwak czasu pokazuje stan "
                    "na wybraną datę."),
    "/analizy/nowa": ("Nowa inwestycja: opisz inwestycję zwykłym tekstem albo wrzuć PFU, projekt umowy lub SWZ (PDF, "
                      "DOCX). System rozpoznaje cechy (sektor, podsektor, długość, budżet, termin, formuła, "
                      "finansowanie) i pokazuje je jako chipy do poprawienia; dopyta o brakujące dane. Potem kliknij "
                      "Uruchom analizę: po kilku sekundach dostaniesz raport z podobnymi umowami z BZP."),
    "/analizy": ("Raport analizy: W skrócie, trzy pytania (czy zdążysz w planowanym terminie, czy budżet wystarczy, czy "
                 "zdążysz przed końcem programu finansowania) z szansą i liczbą podobnych umów, lista na co uważać przed "
                 "przetargiem, podobne przypadki, co dopisać do umowy i grupa porównawcza. Zakładki: Czerwony długopis "
                 "(uwagi do PFU z cytatami), Symulacja (co jeśli: krzywe ukończenia i wpływ zmian przed przetargiem), "
                 "Podział ryzyk i pakiet (kto ponosi które ryzyko, pakiet DOCX, PDF, CSV, JSON do akt). Edytuj "
                 "założenia, żeby policzyć wariant."),
    "/projekty": ("Projekty: 22 projekty pilotażowe z opóźnieniem i kosztem wobec umowy; wyszukaj, filtruj, sortuj, "
                  "eksportuj zaznaczone. Karta projektu: co się stało, przebieg od ogłoszenia do wykonania, termin i "
                  "koszt, podobne przypadki, graf powiązań, dokumenty i historia zmian. Wgranie nowego dokumentu "
                  "(protokół, pismo) pokazuje, co się zmieniło w projekcie."),
    "/przeglad": ("Przegląd (ekspert): kolejka decyzji: propozycje AI (przyczyny zmian, ryzyka), rozbieżności w "
                  "danych i powiązania. Wybierz odpowiedź (klawisze 1-4), Zapisz i dalej; każdą decyzję można cofnąć."),
    "/katalog": ("Katalog wiedzy (ekspert): ryzyka R01-R18, podsektory, dokumenty w fazach, listy kontrolne, zapisy "
                 "umowne, wersje i propozycje modelu. Sektory: wod-kan, drogi, budynki publiczne, sieci ciepłownicze."),
    "/zapytaj": ("Zapytaj: pytania o dane (umowy, aneksy, opóźnienia, koszty, województwa) i o samą aplikację; "
                 "odpowiedź można zapisać jako rekord Q-... i pobrać wiersze w CSV."),
    "/zrodla": ("Import i źródła (ekspert): wgraj plik z danymi, agent importu proponuje mapowanie kolumn, robi próbny "
                "import i po zatwierdzeniu wczytuje dane; lista źródeł i uruchomień."),
    "całość": ("ex ante sprawdza nową inwestycję wodno-kanalizacyjną na tle wykonanych umów z BZP (ponad 11 tys.), "
               "z KPO, CRU, TED, KIO i NIK. Ścieżki: Nowa inwestycja (analiza przed przetargiem), Monitoring (umowy w "
               "toku po terminie), Projekty (22 projekty pilotażowe), Zapytaj (pytania o dane), dla eksperta Przegląd "
               "i Katalog."),
}


def guide(route_or_topic: str) -> str:
    key = (route_or_topic or "").strip().lower() or "całość"
    if key in ("całość", "calosc", "wszystko", "aplikacja"):
        return APP_GUIDE["całość"]
    best = max((k for k in APP_GUIDE if k != "całość" and (key == k or key.startswith(k.rstrip("/") + "/") or k == "/")),
               key=len, default=None)
    if best is None:
        best = next((k for k in APP_GUIDE if k.strip("/") and k.strip("/") in key), "całość")
    text_ = APP_GUIDE[best]
    return text_ if best == "całość" else f"{text_}\n\nCała aplikacja: {APP_GUIDE['całość']}"


@dataclass
class Observation:
    text: str                      # what the model reads next
    short: str                     # what the user sees in the step
    sources: list[dict] = field(default_factory=list)
    n: int | None = None


async def _dane(q: str, ctx: dict) -> Observation:
    from riskminer.llm.tasks import nl2sql as N
    out = await N.ask(q, subject=f"agent:{ctx['actor']}")
    a = out.answer or {}
    n = a.get("n")
    txt = a.get("text") or "Brak odpowiedzi."
    return Observation(text=f"{txt} (n = {n})" if n is not None else txt, short=txt[:220],
                       sources=list(a.get("sources") or []), n=n)


async def _dokumenty(q: str, ctx: dict) -> Observation:
    db: AsyncSession = ctx["db"]
    rows = (await db.execute(text("""
        SELECT d.id, coalesce(d.title, d.filename) AS title, ts_headline('simple', c.text, x.q, 'MaxWords=25,MinWords=10') AS hl
        FROM chunk c JOIN document d ON d.id = c.document_id,
             (SELECT websearch_to_tsquery('simple', unaccent(:q)) AS q) x
        WHERE c.tsv @@ x.q AND (d.sensitivity IS NULL OR d.sensitivity = 'public')
        ORDER BY ts_rank(c.tsv, x.q) DESC LIMIT 5"""), {"q": q[:200]})).mappings().all()
    if not rows:
        return Observation(text="Brak dokumentów pasujących do zapytania.", short="nic nie znaleziono")
    lines = [f"[{r['id']}] {r['title']}: {re.sub(r'<[^>]+>', '', r['hl'] or '')}" for r in rows]
    return Observation(text="\n".join(lines), short=f"{len(rows)} dokumentów, np. {rows[0]['title']}",
                       sources=[{"kind": "document", "id": str(r["id"]), "label": r["title"]} for r in rows[:3]])


async def _projekt(q: str, ctx: dict) -> Observation:
    db: AsyncSession = ctx["db"]
    m = re.search(r"RM-\d{4}-\d{3}", q.upper())
    if m:
        rows = (await db.execute(text("SELECT rm_id, title, beneficiary_name, status, value_amount FROM project "
                                      "WHERE rm_id = :r AND is_pilot"), {"r": m.group(0)})).mappings().all()
    else:
        rows = (await db.execute(text("SELECT rm_id, title, beneficiary_name, status, value_amount FROM project "
                                      "WHERE is_pilot AND (title ILIKE :q OR beneficiary_name ILIKE :q) ORDER BY rm_id LIMIT 3"),
                                 {"q": f"%{q.strip()[:80]}%"})).mappings().all()
    if not rows:
        return Observation(text="Nie znaleziono takiego projektu pilotażowego.", short="nie znaleziono")
    lines = [f"{r['rm_id']}: {r['title']} ({r['beneficiary_name']}), status {r['status']}, "
             f"wartość {r['value_amount']} zł" for r in rows]
    return Observation(text="\n".join(lines), short=", ".join(r["rm_id"] for r in rows),
                       sources=[{"kind": "project", "id": r["rm_id"], "label": r["rm_id"]} for r in rows])


async def _monitoring(q: str, ctx: dict) -> Observation:
    from riskminer.monitoring import service as M
    sector = (q or "").strip().lower() or "wod-kan"
    if sector not in ("wod-kan", "drogi", "budynki", "cieplo"):
        sector = "wod-kan"
    res = await M.regions(ctx["db"], "woj", None, "done", "late", M.Filters(sector=sector))
    regs = sorted(res["regions"], key=lambda r: -(r["value"]["value"] or 0) if isinstance(r.get("value"), dict)
                  else 0)[:3]
    top = ", ".join(f"{r['name']} {r['value']['display']}" for r in regs if isinstance(r.get("value"), dict))
    sig = ""
    if sector == "wod-kan":
        n_sig = (await ctx["db"].execute(text("SELECT count(*) FROM v_monitor_signal"))).scalar()
        sig = f" Sygnały (umowy po terminie bez ogłoszenia o wykonaniu): {n_sig}."
    t = f"Sektor {sector}: {res['total']['label']}. Najwięcej po terminie: {top}.{sig}"
    return Observation(text=t, short=t[:220], n=res["total"].get("n"),
                       sources=[{"kind": "query", "id": f"monitoring:{sector}", "label": f"monitoring, n = {res['total'].get('n')}"}])


async def _opis(q: str, ctx: dict) -> Observation:
    t = guide(q or ctx.get("route") or "całość")
    return Observation(text=t, short=t[:160] + ("..." if len(t) > 160 else ""))


TOOLS = {"opis_aplikacji": _opis, "dane": _dane, "dokumenty": _dokumenty, "projekt": _projekt, "monitoring": _monitoring}


def _transcript(question: str, route: str, history: list[tuple[AgentStep, Observation | None]]) -> str:
    parts = [f"<pytanie>{question.strip()[:800]}</pytanie>", f"<ekran>{route}</ekran>"]
    for i, (st, ob) in enumerate(history, 1):
        parts.append(f"<krok {i}> myśl: {st.thought} | narzędzie: {st.action}({st.action_input})"
                     + (f"\nwynik: {ob.text[:1500]}" if ob else "") + f" </krok {i}>")
    return "\n".join(parts)


async def run(question: str, route: str | None, *, actor: str, db: AsyncSession) -> dict[str, Any]:
    route = (route or "/zapytaj")[:120]
    ctx = {"db": db, "actor": actor, "route": route}
    history: list[tuple[AgentStep, Observation | None]] = []
    steps: list[dict] = []
    sources: list[dict] = []
    ns: list[int] = []
    final, last_call = None, None
    for i in range(MAX_TOOL_CALLS + 2):
        force = i >= MAX_TOOL_CALLS
        req = gateway.LLMRequest(task="agent", sensitivity="public", prompt="agent",
                                 parts=[Text(_transcript(question, route, history))], output=AgentStep,
                                 prompt_vars={"route": route}, subject=f"agent:{actor}", max_output_tokens=900,
                                 extra_user=("Masz już wystarczająco informacji: odpowiedz teraz (action = final)."
                                             if force else None))
        res = await gateway.run(req)
        last_call = res.llm_call_id
        st: AgentStep = res.data
        steps.append({"kind": "thinking", "text": st.thought})
        if st.action == "final" or force:
            final = st.final_answer or st.thought
            break
        tool = TOOLS[st.action]
        try:
            ob = await tool(st.action_input, ctx)
        except Exception as e:  # noqa: BLE001 - a failing tool is reported to the model, not to the user as a crash
            ob = Observation(text=f"Narzędzie zwróciło błąd: {type(e).__name__}.", short="błąd narzędzia")
        steps.append({"kind": "tool", "tool": st.action, "label": TOOL_LABEL[st.action], "input": st.action_input,
                      "result": ob.short})
        history.append((st, ob))
        sources += [s for s in ob.sources if s not in sources]
        if ob.n is not None:
            ns.append(ob.n)
    answer = {"code": None, "role": "ai", "role_label": "odpowiedź asystenta na podstawie narzędzi",
              "text": final or "Nie udało się przygotować odpowiedzi.", "bars": [],
              "method": {"kind": "llm", "sql": None, "template": None}, "sources": sources[:6],
              "n": ns[0] if len(ns) == 1 else None, "missing": [],
              "actions": [{"kind": "save", "label": "Zapisz jako rekord", "href": None}]}
    return {"answer": answer, "steps": steps, "llm_call_id": last_call}
