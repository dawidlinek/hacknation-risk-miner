"""Scrape/test report for the jury (docs/scrape.md §7): docs/test_report_sources.md + exports/sources_summary.csv.
Generated from manifests (data/raw/*/manifest.jsonl) and the DB. Re-run: `uv run riskminer report`."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from riskminer.config import REPO_ROOT, settings
from riskminer.connectors.base import LICENCES
from riskminer.db.session import raw_conn

SOURCE_LABEL = {
    "xlsx": "Zestaw organizatora (XLSX, 22 projekty)", "bzp_copy": "BZP: kopia krajowa organizatora",
    "bzp_api": "BZP: API e-Zamówienia (delta na żywo)", "vat_whitelist": "Biała lista VAT", "teryt": "TERYT (TERC)",
    "geo": "Granice administracyjne (GeoJSON)", "mapa_dotacji": "Mapa Dotacji: KPO B3.1.1", "ted": "TED (UE)",
    "kio": "Orzeczenia KIO", "nik": "Wyniki kontroli NIK", "cru": "Centralny Rejestr Umów", "docs_22": "Dokumenty postępowań (22)",
    "docs_sample": "Dokumenty: próba krajowa", "kposk": "KPOŚK", "gus_bdl": "GUS BDL", "gus_price_index": "GUS: wskaźnik cen",
    "fe_projects": "Lista projektów FE", "nfosigw": "NFOŚiGW", "bip_22": "BIP (22 gminy)", "gus_bir": "GUS BIR (REGON)",
    "krs": "KRS", "bk2021": "Baza Konkurencyjności", "bzp_roads": "BZP: drogi (pakiet W9)",
}
PROJECT_SOURCES = ["mapa_dotacji", "ted", "kio", "nik", "cru", "vat_whitelist", "bzp_api", "docs_22", "bip_22"]


def _manifest_stats() -> dict[str, dict]:
    out = {}
    raw = settings().raw_dir
    if not raw.exists():
        return out
    for d in sorted(p for p in raw.iterdir() if p.is_dir()):
        m = d / "manifest.jsonl"
        if not m.exists():
            continue
        st: Counter = Counter()
        n = nbytes = 0
        last = None
        runs = set()
        lic = None
        with m.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                n += 1
                st[e.get("status")] += 1
                nbytes += e.get("bytes") or 0
                last = max(last or "", e.get("fetched_at") or "")
                runs.add(e.get("run_id"))
                lic = lic or e.get("licence")
        out[d.name] = {"manifest_lines": n, **{k: v for k, v in st.items() if k}, "bytes": nbytes, "last": last,
                       "runs": len(runs), "licence": lic or LICENCES.get(d.name, "")}
    return out


def _n(x) -> str:
    return f"{int(x or 0):,}".replace(",", "\u00a0")


def _fmt_dt(x) -> str:
    if not x:
        return "-"
    if isinstance(x, datetime):
        return x.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return str(x).replace("T", " ").replace("Z", " UTC")


async def generate() -> dict:
    ms = _manifest_stats()
    async with raw_conn() as conn:
        loaded = {r["k"]: r["n"] for r in await conn.fetch("SELECT source_kind k, count(*) n FROM external_record GROUP BY 1")}
        loaded["bzp_copy"] = await conn.fetchval("SELECT count(*) FROM notice WHERE channel='bzp_copy'")
        loaded["bzp_api"] = await conn.fetchval("SELECT count(*) FROM notice WHERE channel='bzp_api'")
        loaded["bzp_roads"] = await conn.fetchval("SELECT count(*) FROM notice WHERE channel='bzp_roads'")
        loaded["xlsx"] = await conn.fetchval("SELECT count(*) FROM project WHERE is_pilot")
        kinds = defaultdict(dict)
        for r in await conn.fetch("SELECT source_kind, kind, count(*) n FROM external_record GROUP BY 1, 2"):
            kinds[r["source_kind"]][r["kind"]] = r["n"]
        docs = defaultdict(Counter)
        for r in await conn.fetch("SELECT data->>'source' s, fetch_state, count(*) n FROM document GROUP BY 1, 2"):
            docs[r["s"]][r["fetch_state"]] = r["n"]
        checks = defaultdict(Counter)
        for r in await conn.fetch("SELECT source_kind, result, count(*) n FROM source_check GROUP BY 1, 2"):
            checks[r["source_kind"]][r["result"]] = r["n"]
        src_rows = {r["kind"]: dict(r) for r in await conn.fetch(
            "SELECT kind, count(*) files, max(retrieved_at) last, max(licence) licence FROM source GROUP BY kind")}
        runs = {r["connector"]: dict(r) for r in await conn.fetch(
            "SELECT DISTINCT ON (connector) connector, started_at, finished_at, status, stats FROM ingestion_run "
            "ORDER BY connector, started_at DESC")}
        core = {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in (
            "notice", "procedure", "lot", "contract", "contract_performance", "contract_change", "organization", "evidence")}
        latest = await conn.fetchval("SELECT count(*) FROM notice WHERE is_latest")
        rel = {r["relevance"]: r["n"] for r in await conn.fetch(
            "SELECT relevance, count(*) n FROM procedure WHERE sector = 'wod-kan' GROUP BY 1")}
        rc = await conn.fetchrow("""
            SELECT count(*) n, count(*) FILTER (WHERE late) late, count(*) FILTER (WHERE cost_dev_pct > 0.5) overrun,
                   (SELECT count(*) FROM contract_performance WHERE is_duplicate) dups
            FROM rc_contract WHERE relevance = 'core' AND scope_kind = 'works' AND sector = 'wod-kan'""")
        sect = {r["sector"]: dict(r) for r in await conn.fetch("""
            SELECT p.sector, count(DISTINCT p.id) procs, count(DISTINCT n.id) notices
            FROM procedure p LEFT JOIN notice n ON n.procedure_id = p.id AND n.is_latest GROUP BY p.sector""")}
        projects = await conn.fetch("SELECT * FROM project WHERE is_pilot ORDER BY rm_id")
        rows = []
        for p in projects:
            link = await conn.fetchrow("""SELECT pp.method, pp.score, pr.ocid, pr.contract_notice_no, pr.notice_types,
                       (SELECT count(*) FROM notice n WHERE n.ocid = pr.ocid AND n.is_latest) n_notices,
                       (SELECT count(*) FROM contract c WHERE c.procedure_id = pr.id) n_contracts,
                       (SELECT count(*) FROM contract_performance f WHERE f.procedure_id = pr.id) n_perf,
                       (SELECT count(*) FROM contract_change ch WHERE ch.procedure_id = pr.id AND ch.kind IN ('change_notice', 'performance_block')) n_changes,
                       lc.reference_verdict, pp.updated_at
                FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id
                LEFT JOIN link_candidate lc ON lc.id = pp.link_candidate_id
                WHERE pp.project_id = $1 AND pp.method <> 'cross_reference_related'
                ORDER BY pp.score DESC NULLS LAST LIMIT 1""", p["id"])
            chk = {r["source_kind"]: r for r in await conn.fetch(
                "SELECT * FROM source_check WHERE subject_type='organization' AND subject_key=$1", p["beneficiary_nip"])}
            chk.update({r["source_kind"]: r for r in await conn.fetch(
                "SELECT * FROM source_check WHERE subject_type='project' AND subject_key=$1", p["rm_id"])})
            hints = {r["k"]: r for r in await conn.fetch(
                "SELECT split_part(right_ref, ':', 1) k, max(score) score, count(*) n FROM link_candidate "
                "WHERE left_table='project' AND left_id=$1 AND right_table='external_record' GROUP BY 1", p["id"])}
            dstates = Counter({r["fetch_state"]: r["n"] for r in await conn.fetch(
                "SELECT fetch_state, count(*) n FROM document WHERE project_id=$1 GROUP BY 1", p["id"])})
            issues = await conn.fetch("SELECT code, title FROM review_item WHERE project_id=$1 AND kind='discrepancy' ORDER BY id",
                                      p["id"])
            rows.append({"p": p, "link": link, "chk": chk, "hints": hints, "docs": dstates, "issues": issues})
        lq = await conn.fetchrow("""SELECT count(*) FILTER (WHERE reference_verdict='correct') correct,
              count(*) FILTER (WHERE reference_verdict='wrong') wrong,
              count(*) FILTER (WHERE reference_verdict IS NULL AND rank = 1) unchecked,
              count(*) FILTER (WHERE review_status IN ('approved','edited')) expert_ok,
              count(*) FILTER (WHERE review_status = 'rejected') expert_rejected
            FROM link_candidate WHERE left_table='project' AND right_table='procedure' AND (rank = 1 OR rank IS NULL)""")
        ln_run = await conn.fetchval("SELECT stats->>'report_pl' FROM ingestion_run WHERE connector='link_national' "
                                     "AND status='ok' ORDER BY started_at DESC LIMIT 1")
        search = await conn.fetchrow("SELECT (SELECT count(DISTINCT document_id) FROM chunk) docs, "
                                     "(SELECT count(*) FROM document_page) pages, (SELECT count(*) FROM chunk) chunks, "
                                     "(SELECT count(*) FROM document WHERE ocr) ocr_docs, "
                                     "(SELECT count(*) FROM document WHERE (data->>'needs_ocr')::boolean) needs_ocr, "
                                     "(SELECT count(*) FROM document WHERE (data->>'ocr_low_confidence')::boolean) ocr_low")
        cru = await conn.fetchrow("""SELECT count(*) n, count(*) FILTER (WHERE (data->>'detail_fetched')::boolean) det,
                count(*) FILTER (WHERE (data->>'water_relevant')::boolean) w,
                count(*) FILTER (WHERE (data->>'water_relevant')::boolean AND (data->>'detail_fetched')::boolean) w_det
            FROM external_record WHERE kind = 'cru_agreement'""")
        pp_methods = {r["method"]: r["n"] for r in await conn.fetch(
            "SELECT method, count(*) n FROM project_procedure WHERE method <> 'cross_reference_related' GROUP BY 1")}

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    all_sources = sorted(set(ms) | set(src_rows) | {"xlsx", "bzp_copy"}, key=lambda s: list(SOURCE_LABEL).index(s)
                         if s in SOURCE_LABEL else 99)
    summary = []
    for s in all_sources:
        m = ms.get(s, {})
        sr = src_rows.get(s, {})
        run = runs.get(s) or runs.get("bzp" if s == "bzp_copy" else s) or {}
        recs = loaded.get(s, 0) + sum(docs.get(s, {}).values())
        summary.append({
            "source": s, "label": SOURCE_LABEL.get(s, s),
            "queries_run": m.get("manifest_lines", sr.get("files", 0)),
            "fetched_ok": m.get("ok", sr.get("files", 0) if s in ("xlsx", "bzp_copy") else 0),
            "empty": m.get("empty", 0), "blocked": m.get("blocked", 0), "errors": m.get("error", 0),
            "bytes": m.get("bytes", 0), "records_loaded": recs,
            "checks": ";".join(f"{k}={v}" for k, v in sorted(checks.get(s, {}).items())),
            "record_kinds": ";".join(f"{k}={v}" for k, v in sorted(kinds.get(s, {}).items())),
            "last_run": _fmt_dt(m.get("last") or sr.get("last") or run.get("finished_at")),
            "licence": m.get("licence") or sr.get("licence") or LICENCES.get(s, ""),
            "location": f"data/raw/{s}/" if s not in ("xlsx", "bzp_copy") else (
                "materials/starter/Risk_Miner_dane_projekty.xlsx" if s == "xlsx" else
                "materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl"),
        })
    exp = Path(settings().exports_dir)
    exp.mkdir(parents=True, exist_ok=True)
    with (exp / "sources_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()) if summary else ["source"])
        w.writeheader()
        w.writerows(summary)

    L = [f"# Raport z testu źródeł: Risk Miner", "",
         f"_Wygenerowano automatycznie: {now} (`uv run riskminer report`). Dane: manifesty `data/raw/*/manifest.jsonl` "
         "i baza (tabele `source`, `ingestion_run`, `source_check`, `link_candidate`, `review_item`)._", "",
         "## 1. Podsumowanie per źródło", "",
         "| Źródło | Zapytania | Pobrane OK | Puste | Zablokowane | Błędy | Rekordy w bazie | Sprawdzenia | Ostatni przebieg | Licencja | Lokalizacja |",
         "|---|---:|---:|---:|---:|---:|---:|---|---|---|---|"]
    for s in summary:
        L.append(f"| {s['label']} (`{s['source']}`) | {s['queries_run']} | {s['fetched_ok']} | {s['empty']} | {s['blocked']} | "
                 f"{s['errors']} | {s['records_loaded']} | {s['checks'] or '-'} | {s['last_run']} | {s['licence']} | `{s['location']}` |")
    L += ["", "Rodzaje rekordów: " + "; ".join(f"`{s['source']}`: {s['record_kinds']}" for s in summary if s["record_kinds"]), "",
          "## 2. Baza przypadków z BZP (krajowo)", "",
          f"- Ogłoszenia: **{_n(core['notice'])}** (najnowsze wersje: {_n(latest)}; zastąpione wersje: {_n(core['notice'] - latest)})",
          f"- Postępowania (OCID): **{_n(core['procedure'])}**; części: {_n(core['lot'])}; umowy: {_n(core['contract'])}; "
          f"ogłoszenia o wykonaniu: {_n(core['contract_performance'])} (w tym {_n(rc['dups'])} ponownie opublikowanych dla tej samej umowy); "
          f"zmiany umów: {_n(core['contract_change'])}; organizacje: {_n(core['organization'])}; "
          f"dowody (pola formularzy): {_n(core['evidence'])}",
          f"- Sektory: " + "; ".join(f"`{k}`: {_n(v['procs'])} postępowań, {_n(v['notices'])} ogłoszeń" for k, v in sorted(sect.items()))
          + " (pakiet `drogi` = wycinek BZP CPV 45233* 2024–2026 do demonstracji „nowy sektor w 60 s”; liczby poniżej dotyczą wod-kan)",
          f"- Trafność wod-kan (klasyfikator na poziomie postępowania): " + ", ".join(f"{k}: {_n(v)}" for k, v in sorted(rel.items(), key=lambda kv: str(kv[0]))),
          f"- Klasa referencyjna `rc_contract` (core, roboty, wykonane, bez duplikatów): n = **{_n(rc['n'])}**; "
          f"po terminie (pole 5.3 = Nie): {_n(rc['late'])} ({(rc['late'] / rc['n'] * 100 if rc['n'] else 0):.1f}%); "
          f"wypłata > wartość umowy o >0,5%: {_n(rc['overrun'])}",
          "", "## 3. Projekty pilotażowe (22)", "",
          "| Projekt | Powiązanie BZP (metoda, pewność) | Łańcuch (ogł./umowy/wyk./zmiany) | Wzorzec | Mapa Dotacji | TED | KIO | CRU | Biała lista | API na żywo | Dokumenty | Rozbieżności |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]

    def chk(r, s):
        c = r["chk"].get(s)
        h = r["hints"].get({"mapa_dotacji": "kpo_project"}.get(s, "~"))
        if s == "mapa_dotacji" and h:
            return f"znaleziono ({h['score']:.2f})"
        if not c:
            return "-"
        lab = {"found": "znaleziono", "not_found": "szukano, brak", "blocked": "zablokowane", "error": "błąd", "partial": "częściowo"}
        return f"{lab.get(c['result'], c['result'])} ({c['n_relevant']}/{c['n_hits']}) {_fmt_dt(c['checked_at'])[:10]}"

    for r in rows:
        p, ln = r["p"], r["link"]
        link = f"{ln['method']} ({ln['score']:.2f}) `{ln['contract_notice_no'] or ln['ocid'][:24]}`" if ln else "**brak**"
        chain = f"{ln['n_notices']}/{ln['n_contracts']}/{ln['n_perf']}/{ln['n_changes']}" if ln else "-"
        ref = {"correct": "✔ zgodne", "wrong": "✘ niezgodne"}.get(ln["reference_verdict"] if ln else None, "-")
        d = r["docs"]
        dd = (f"{d.get('found', 0)} pobr.; " + ", ".join(f"{k}: {v}" for k, v in d.items() if k != "found")) if d else "-"
        iss = "; ".join(i["code"] for i in r["issues"]) or "-"
        L.append(f"| {p['rm_id']} {p['beneficiary_name']} | {link} | {chain} | {ref} | {chk(r, 'mapa_dotacji')} | {chk(r, 'ted')} | "
                 f"{chk(r, 'kio')} | {chk(r, 'cru')} | {chk(r, 'vat_whitelist')} | {chk(r, 'bzp_api')} | {dd} | {iss} |")
    L += ["", "### Rozbieżności wykryte w zestawie organizatora", ""]
    for r in rows:
        for i in r["issues"]:
            L.append(f"- **{r['p']['rm_id']}** (wiersz {(r['p']['dataset_row'] or {}).get('Lp.', '?')}): {i['title']}")
    L += ["", "## 4. Jakość powiązań", "",
          f"- Metody powiązania 22 projektów: " + ", ".join(f"{k}: {v}" for k, v in pp_methods.items()),
          f"- Względem zbioru wzorcowego (research/bzp_linking, 22/22 zweryfikowane ręcznie): poprawne **{lq['correct']}**, "
          f"błędne {lq['wrong']}, niesprawdzone {lq['unchecked']}.",
          f"- Po przeglądzie eksperta: zatwierdzone {lq['expert_ok']}, odrzucone {lq['expert_rejected']} "
          "(kolumna `review_status` w `link_candidate`).",
          "- Progi: automatyczna akceptacja ≥ 0,90; do przeglądu 0,60–0,90; odrzucenie < 0,60 (powiązania rozmyte pokazują cechy i wynik).",
          ""] + ([ln_run.replace("### Powiązania krajowe", "### 4a. Powiązania krajowe"), ""] if ln_run else []) + [
          "## 4b. Tekst dokumentów i wyszukiwanie", "",
          f"- Dokumenty z tekstem w indeksie pełnotekstowym: {_n(search['docs'])}; strony: {_n(search['pages'])}; "
          f"fragmenty (chunk): {_n(search['chunks'])}. Wyszukiwanie: `GET /api/search`.",
          f"- OCR (Tesseract, model pol, WCSS): dokumenty po OCR {_n(search['ocr_docs'])}; skany bez warstwy tekstowej "
          f"czekające na OCR: {_n(search['needs_ocr'])}; z niską pewnością OCR (średnio poniżej 0,6, stan NIECZYTELNY "
          f"przy cytatach): {_n(search['ocr_low'])}.",
          "", "## 5. Ograniczenia i stany dowodowe", "",
          "- „Szukano, nie znaleziono” jest zapisywane jawnie (`source_check`): brak wyniku ≠ brak zdarzenia.",
          "- Dokumenty niedostępne mają stan: `not_in_package`, `blocked` (zabezpieczenie platformy, którego nie obchodzimy), "
          "`link_dead`, `not_applicable`.",
          "- Wyjątek od robots.txt: platformazakupowa.pl i logintrade.net blokują w robots.txt pobieranie załączników. "
          "Za zgodą operatorów tych platform (zgłoszoną przez zespół 21.11.2026) pobieramy publiczne linki do załączników "
          "co 5 s; każde takie pobranie ma w manifeście notatkę `robots.txt override`. Pozostałe serwisy: robots.txt i Crawl-delay respektowane.",
          "- Dane osobowe kontaktowe nie są kopiowane do tabel znormalizowanych ani eksportów (RODO).",
          ] + ([f"- Centralny Rejestr Umów: szczegóły umowy (w tym lista zmian i aneksów) pobrane dla {_n(cru['det'])} z "
                f"{_n(cru['n'])} umów (wod-kan: {_n(cru['w_det'])} z {_n(cru['w'])}). Serwis stoi za zaporą WAF; gdy pokazał "
                "stronę wyzwania, pobieranie zatrzymano i zapisano jako `blocked` (nie obchodzimy zabezpieczeń), wznawiamy po "
                "przerwie. Liczby zmian z CRU dotyczą tylko umów z pobranymi szczegółami."]
               if cru and cru["n"] and cru["det"] < cru["n"] else []) + [""]
    out = REPO_ROOT / "docs" / "test_report_sources.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return {"report": str(out), "summary_csv": str(exp / "sources_summary.csv"), "sources": len(summary)}
