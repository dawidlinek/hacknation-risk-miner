"""National record linking (PLAN §6.3), a re-runnable stage: `link_national`.

1. KPO B3.1.1 projects (Mapa Dotacji, `external_record` kind=kpo_project) -> BZP procedures.
   Mapa Dotacji shows neither the KPO number nor a NIP (scrape.md §3.3), so the beneficiary is first resolved to
   BZP buyer NIP(s): gminas by their TERYT unit (name + kind: rural vs urban, so Gmina Elbląg is not Gmina Miasto
   Elbląg) and province (two Bobrowniki, two Zakrzew), exact core name (Kamionka is not Kamionka Wielka);
   utility companies by fuzzy name within the province, confirmed by the buyer's city lying in the TERYT powiat.
   Each buyer's wod-kan procedures from 2023 on are scored on IDF-weighted title/description overlap, water/sewage
   relevance or CPV, date plausibility (KPO B3.1.1 era) and value proximity (KPO total vs contract sum, paid sum,
   single lot, estimate x 1.23); a match to the grosz is decisive. Top 3 per project are kept.
2. CRU agreements (`external_record` kind=cru_agreement, register starts 2026-07-01) -> BZP contracts.
   Buyer by NIP, else REGON -> NIP (BZP field 1.4, organization.regon, CRU rows carrying both); then the buyer's
   contracts signed within ±45 days, scored on contractor NIP (or name), value (±1 %, also x/÷ 1.23 for the
   unknown VAT basis of CRU), date distance and subject token overlap. Top 3 per agreement are kept.

Rows go to `link_candidate` (unique key left_table, left_id, right_table, right_ref, method); rows the expert has
approved, edited or rejected are never touched. The 10 pilot projects whose KPO record and BZP procedure are known
(link_pilot) are used only AFTER scoring, as a reference check (precision/recall), never as an input feature.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from rapidfuzz import fuzz

from riskminer.ingest import ids
from riskminer.ingest.dbutil import audit, upsert_copy
from riskminer.ingest.linking import STOP as _PILOT_STOP

ACCEPT, REVIEW = 0.9, 0.6          # PLAN §6.3 thresholds (accept still reviewable)
TOP_N = 3
KPO_METHOD = "beneficiary+value+text"
CRU_METHOD = "buyer_id+contractor+value+date"
KPO_SINCE = date(2023, 1, 1)
KPO_ERA = (date(2024, 1, 1), date(2026, 6, 30))   # B3.1.1 calls 2024-2025, completion by mid 2026
CRU_WINDOW = 45                                   # days between CRU signed date and BZP contract signed_on
CRU_MIN_KEEP = 0.30                               # below this a same-buyer contract is noise, not a candidate
KPO_MIN_KEEP = 0.20
VAT = 1.23
PROTECTED_STATUS = ("approved", "edited", "rejected")   # expert decisions: never overwritten or deleted here

# water/sewage CPV prefixes (stricter than linking.WODKAN_CPV, whose "4523" also covers roads 45233)
WATER_CPV = ("45231", "45232", "45252", "45247", "45330", "45332", "4524", "71322", "44163", "65")
_EXTRA_STOP = ("ul ulicy ulica nr dz obreb gm pn zadanie zadania realizacja wykonanie inwestycji projektu "
               "przedsiewziecia polega celem jest sa ktore ktora ktory zostanie zostana bedzie przez jego tym ich "
               "ramach zamowienia czesci mieszkancow miejscowosciach terenach obszarze obszarach oraz lub takze rowniez")
STOP = _PILOT_STOP | set(_EXTRA_STOP.split(" "))


# ======================================================================================
# Text helpers
# ======================================================================================

def _norm(s: str | None) -> str:
    """Folded, punctuation-free, single-spaced."""
    return re.sub(r"[^a-z0-9]+", " ", ids.fold(s or "")).strip()


_LEGAL = re.compile(r"\b(?:spolk[aiey]|sp)\s*z\s*(?:ograniczona\s+odpowiedzialnoscia|o\s*o)\b|\bspolka\s+akcyjna\b"
                    r"|\bspolka\s+(?:jawna|komandytowa)\b|\bsp\s+[jk]\b|\bs\s*a$")


def norm_org(s: str | None) -> str:
    """Organisation name for fuzzy comparison: folded, legal form removed."""
    return re.sub(r"\s+", " ", _LEGAL.sub(" ", _norm(s))).strip()


_GMINA = re.compile(
    r"^(?P<pre>urzad miasta i gminy|urzad gminy i miasta|urzad gminy|urzad miasta|urzad miejski|"
    r"gmina miejsko wiejska|gmina wiejska|gmina miejska|gmina miasto|gmina miasta|gmina i miasto|miasto i gmina|"
    r"miasto gmina|gmina|gminy|miasto)\s+(?P<core>.+)$")
_KIND = {"gmina miejska": "urban", "gmina miasto": "urban", "gmina miasta": "urban", "miasto": "urban",
         "urzad miasta": "urban", "miasto i gmina": "mixed", "gmina i miasto": "mixed", "miasto gmina": "mixed",
         "gmina miejsko wiejska": "mixed", "urzad miasta i gminy": "mixed", "urzad gminy i miasta": "mixed",
         "urzad miejski": "mixed", "gmina wiejska": "rural", "urzad gminy": "rural", "gmina": "plain", "gminy": "plain"}
# TERYT rodz of the KPO gmina -> how compatible a buyer named with a given kind marker is
_COMPAT = {"1": {"plain": 1.0, "urban": 1.0, "mixed": 0.0, "rural": 0.0},
           "2": {"plain": 1.0, "rural": 1.0, "mixed": 0.0, "urban": 0.0},
           "3": {"plain": 1.0, "mixed": 1.0, "rural": 0.85, "urban": 0.7}}
_KIND_PL = {"urban": "gmina miejska", "mixed": "gmina miejsko-wiejska", "rural": "gmina wiejska", "plain": "gmina"}


_SUFFIX_OK = re.compile(r"^(?:woj|wojewodztwo|powiat|pow|urzad|ul|ulica|al|pl|z siedziba|siedziba|gmina|gminy|\d)")


def core_matches(core: str, gname: str) -> bool:
    """Exact gmina core, or the core followed by an address/office suffix ('bobowa woj malopolskie powiat gorlicki',
    'lubichowo urzad gminy lubichowo'); never a longer name ('kamionka wielka' is not 'kamionka')."""
    if core == gname:
        return True
    return core.startswith(gname + " ") and bool(_SUFFIX_OK.match(core[len(gname) + 1:]))


def parse_gmina(name: str | None) -> tuple[str, str, bool] | None:
    """'Gmina Miasto Elbląg na prawach powiatu' -> ('elblag', 'urban', False); 'Urząd Gminy w Zakrzewie' ->
    ('zakrzewie', 'rural', True) (locative, not comparable by name). None for non-gmina names."""
    name = re.sub(r"^(Gmina)(?=[A-ZĄĆĘŁŃÓŚŹŻ])", r"\1 ", (name or "").strip())
    n = norm_org(name)
    if n.endswith(" commune"):                   # 'Mircze Commune' (English form seen on Mapa Dotacji)
        n = "gmina " + n[: -len(" commune")]
    m = _GMINA.match(n)
    if not m:
        return None
    pre, core = m.group("pre"), m.group("core")
    kind = _KIND[pre]
    if "na prawach powiatu" in core:
        kind, core = "urban", core.replace("na prawach powiatu", " ")
    core = re.sub(r"^(?:uzdrowiskowa|miejska|wiejska)\s+", "", core)
    locative = core.startswith("w ")
    core = re.sub(r"^w\s+", "", core)
    core = re.sub(r"\s+", " ", core).strip()
    if not core or pre == "miasto" and core.startswith(("stoleczne", "st ")):
        return None
    return core, kind, locative


def tok(s: str | None) -> set[str]:
    return {t[:6] for t in re.findall(r"[a-z0-9]{3,}", ids.fold(s or "")) if t not in STOP}


class Idf:
    def __init__(self, docs: list[set[str]]):
        self.n = len(docs)
        self.df = Counter(t for d in docs for t in d)
        self.max = math.log(self.n + 1) + 1

    def w(self, t: str) -> float:
        d = self.df.get(t)
        return self.max if not d else math.log((self.n + 1) / (d + 1)) + 1

    def cos(self, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        num = sum(self.w(t) ** 2 for t in a & b)
        return num / math.sqrt(sum(self.w(t) ** 2 for t in a) * sum(self.w(t) ** 2 for t in b))

    def cont(self, part: set[str], whole: set[str]) -> float:
        """Weighted share of `part` found in `whole`."""
        tot = sum(self.w(t) for t in part)
        return sum(self.w(t) for t in part & whole) / tot if tot else 0.0

    def rare(self, toks: set[str], k: int = 6) -> list[str]:
        return sorted(toks, key=lambda t: -self.w(t))[:k]


def _pln(x: float | Decimal | None) -> str:
    if x is None:
        return "brak"
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",") + " zł"


def _dec(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + "%"


def _count(it) -> dict:
    return dict(Counter(str(x) for x in it))


# ======================================================================================
# Buyer index (BZP side) and beneficiary resolution
# ======================================================================================

@dataclass
class Buyer:
    key: str                                             # NIP, or '~<name>|<province>' when BZP has no NIP
    nip: str | None
    names: set[str] = field(default_factory=set)
    provinces: set[str] = field(default_factory=set)
    cities: set[str] = field(default_factory=set)        # normalised
    n_proc: int = 0
    norm_names: set[str] = field(default_factory=set)
    gmina: list[tuple[str, str, bool]] = field(default_factory=list)   # parsed gmina names


def buyer_key(nip: str | None, name: str | None, province: str | None) -> str:
    return nip if nip else f"~{norm_org(name)}|{province or ''}"


async def _buyers(conn) -> dict[str, Buyer]:
    out: dict[str, Buyer] = {}
    for r in await conn.fetch("""SELECT buyer_nip, buyer_name, province, city, count(*) n FROM procedure
                                 WHERE buyer_nip IS NOT NULL OR buyer_name IS NOT NULL GROUP BY 1, 2, 3, 4"""):
        k = buyer_key(r["buyer_nip"], r["buyer_name"], r["province"])
        b = out.setdefault(k, Buyer(k, r["buyer_nip"]))
        b.n_proc += r["n"]
        if r["buyer_name"]:
            b.names.add(r["buyer_name"].strip())
        if r["province"]:
            b.provinces.add(r["province"])
        if r["city"]:
            b.cities.add(_norm(r["city"]))
    for r in await conn.fetch("SELECT nip, name, province, city FROM organization WHERE nip = ANY($1::text[])",
                              list(out)):
        b = out[r["nip"]]
        b.names.add(r["name"].strip())
        if r["province"]:
            b.provinces.add(r["province"])
        if r["city"]:
            b.cities.add(_norm(r["city"]))
    for b in out.values():
        b.norm_names = {norm_org(n) for n in b.names} - {""}
        b.gmina = [g for g in (parse_gmina(n) for n in b.names) if g]
    return out


@dataclass
class Teryt:
    gmi: dict[str, dict]                     # terc7 -> row
    by_name: dict[str, list[str]]            # normalised gmina name -> [terc7]
    pow_names: dict[str, set[str]]           # powiat terc4 -> normalised gmina + town names in it


async def _teryt(conn) -> Teryt:
    gmi, by_name, pow_names = {}, defaultdict(list), defaultdict(set)
    for r in await conn.fetch("SELECT terc, level, name, kind, woj, rodz FROM ref_teryt WHERE level IN ('gmi', 'part')"):
        n = _norm(r["name"])
        if len(r["terc"]) == 7:
            pow_names[r["terc"][:4]].add(n)
        if r["level"] == "gmi":
            gmi[r["terc"]] = dict(r)
            by_name[n].append(r["terc"])
    return Teryt(gmi, by_name, pow_names)


_WOJ_CODE = {ids.fold(v): k for k, v in ids.WOJ.items()}


def _kpo_geo(rec, ter: Teryt) -> tuple[list[str], str | None, str | None]:
    """-> (candidate gmina TERC7 list, province PLxx or None, powiat TERC4 or None)."""
    t = (rec["teryt"] or "").strip()
    prov = None
    if len(t) >= 2:
        prov = "PL" + t[:2]
    elif _WOJ_CODE.get(ids.fold(rec["province"] or "")):
        prov = "PL" + _WOJ_CODE[ids.fold(rec["province"] or "")]
    powiat = t[:4] if len(t) >= 4 else None
    if len(t) == 7 and t in ter.gmi:
        return [t], prov, powiat
    g = parse_gmina(rec["buyer_name"])
    if not g or g[2]:
        return [], prov, powiat
    cands = [c for c in ter.by_name.get(g[0], []) if c.startswith(t)] if t else ter.by_name.get(g[0], [])
    res = ((rec["data"] or {}).get("teryt_resolution") or {}).get("candidates") or []
    cands = cands or [c for c in res if c in ter.gmi]
    if len(cands) == 1:
        prov = prov or "PL" + cands[0][:2]
        powiat = powiat or cands[0][:4]
    return cands, prov, powiat


def resolve_beneficiary(rec, buyers_by_prov: dict[str, list[Buyer]], all_buyers: list[Buyer],
                        ter: Teryt) -> tuple[list[dict], dict]:
    """KPO beneficiary -> [{nip, score, how, name}] (best first), plus a description of the geography used."""
    gminas, prov, powiat = _kpo_geo(rec, ter)
    geo = {"province": prov, "powiat": powiat, "gminas": gminas}
    found: dict[str, dict] = {}

    def add(b: Buyer, score: float, how: str):
        if score > found.get(b.key, {}).get("score", 0):
            found[b.key] = {"key": b.key, "nip": b.nip, "score": round(score, 3), "how": how + ("" if b.nip else
                            ", w BZP bez NIP"), "name": min(b.names)}

    for terc in gminas:
        g = ter.gmi[terc]
        gp, gname, rodz = "PL" + terc[:2], _norm(g["name"]), g["rodz"] or "2"
        pnames = ter.pow_names.get(terc[:4], set())
        for b in buyers_by_prov.get(gp, []):
            city_seat = gname in b.cities
            city_pow = bool(b.cities & pnames)
            for core, kind, loc in b.gmina:
                compat = _COMPAT.get(rodz, _COMPAT["2"]).get(kind, 0.0)
                if not compat:
                    continue
                if not loc and core_matches(core, gname):
                    s = compat * (1.0 if (city_seat or city_pow) else 0.9)
                    add(b, s, "nazwa gminy" + (f" ({_KIND_PL[kind]})" if kind != "plain" else "") + " i województwo zgodne"
                              + ("" if (city_seat or city_pow) else ", siedziba spoza powiatu"))
                elif loc and city_seat:
                    add(b, 0.85 * compat, "urząd gminy w miejscowości będącej siedzibą gminy")
    if not found and not gminas:
        # utility company or an unparsed name: fuzzy name in the province (national when unknown)
        nb = norm_org(rec["buyer_name"])
        pool = buyers_by_prov.get(prov, []) if prov else all_buyers
        pnames = ter.pow_names.get(powiat, set()) if powiat else set()
        hits = []
        for b in pool:
            r = max((max(fuzz.token_sort_ratio(nb, n), 0.92 * fuzz.token_set_ratio(nb, n)) for n in b.norm_names),
                    default=0) / 100
            if r >= 0.85:
                city_ok = bool(b.cities & pnames) if pnames else None
                hits.append((b, r, city_ok))
        top_r = max((r for _, r, _ in hits), default=0)
        generic = sum(1 for _, r, _ in hits if r >= top_r - 0.03) > 1      # several near-equal names (generic name)
        for b, r, city_ok in hits:
            s = r * (1.0 if city_ok else 0.8 if city_ok is False else 0.9)
            if generic and not city_ok:
                s *= 0.8
            if s >= 0.75:
                add(b, s, f"podobna nazwa ({round(r * 100)}%)"
                          + (", siedziba w powiecie z TERYT" if city_ok else ", siedziba poza powiatem" if city_ok is False
                             else "") + (", nazwa niejednoznaczna" if generic else ""))
    out = sorted(found.values(), key=lambda x: -x["score"])[:4]
    strong = [x for x in out if x["score"] >= 0.9 and x["nip"]]
    if len(strong) > 1:
        same_name_units = len(gminas) > 1 or any(
            sum(1 for t in ter.by_name.get(_norm(ter.gmi[g]["name"]), []) if t[:2] == g[:2]) > 1 for g in gminas)
        if not gminas or same_name_units:
            geo["ambiguous"] = True              # e.g. two gminas Rogowo in one voivodeship: evidence must decide
            for x in out:
                x["score"] = round(x["score"] * 0.93, 3)
        else:                                    # one TERYT gmina, several NIPs in BZP (gmina vs its office)
            geo["several_nips"] = True
            for x in strong:
                x["how"] += ", kilka NIP tej samej gminy w BZP"
    return out, geo


# ======================================================================================
# 1. KPO projects -> procedures
# ======================================================================================

def _water(cpv_all, relevance) -> float:
    if relevance == "core":
        return 1.0
    if relevance == "component":
        return 0.8
    if any((c or "").startswith(WATER_CPV) for c in cpv_all or []):
        return 0.6
    return 0.4 if relevance == "cpv_only" else 0.0


def _kpo_date(d: date | None) -> float:
    if d is None:
        return 0.5
    if KPO_ERA[0] <= d <= KPO_ERA[1]:
        return 1.0
    if date(2023, 7, 1) <= d < KPO_ERA[0] or KPO_ERA[1] < d <= date(2026, 8, 31):
        return 0.6
    return 0.3 if d >= KPO_SINCE and d < date(2023, 7, 1) else 0.2


def _kpo_value(kpo: float | None, contracts: list[dict], est: float | None) -> dict:
    """Closest BZP amount to the KPO total. Contract values and payments are gross; the estimate is net (x1.23)."""
    if not kpo:
        return {"score": None}
    opts: dict[str, float] = {}
    vals = [c for c in contracts if c["value"]]
    if vals:
        opts["suma wartości umów"] = sum(c["value"] for c in vals)
    paid = [c for c in contracts if c["paid"]]
    if paid:
        opts["suma wypłat"] = sum(c["paid"] for c in paid)
    if len(contracts) > 1:
        for c in contracts:
            if c["value"]:
                opts[f"umowa, część {c['lot']}"] = c["value"]
            if c["paid"]:
                opts[f"wypłata, część {c['lot']}"] = c["paid"]
    best, rel, exact = None, None, False
    for k, v in opts.items():
        r = abs(v - kpo) / kpo
        if rel is None or r < rel:
            best, rel, exact = k, r, abs(v - kpo) <= 0.01
    from_est = False
    if est:
        r = abs(est * VAT - kpo) / kpo
        if rel is None or r < rel - 0.05:       # the estimate only wins when clearly closer
            best, rel, exact, from_est = "wartość szacunkowa netto x 1,23", r, False, True
    if rel is None:
        return {"score": None}
    s = 1.0 if exact else next((v for lim, v in ((0.005, 0.9), (0.02, 0.8), (0.05, 0.65), (0.10, 0.5), (0.20, 0.35),
                                                  (0.35, 0.2)) if rel <= lim), 0.0)
    if from_est:
        s *= 0.7
    amount = est * VAT if from_est else opts[best]
    return {"score": round(s, 3), "basis": best, "bzp_amount": round(amount, 2), "rel_diff": round(rel, 4),
            "exact": exact, "from_estimate": from_est}


def score_kpo(k_title: set[str], k_all: set[str], p: dict, idf: Idf, kpo_value: float | None,
              buyer_score: float) -> tuple[float, dict]:
    cos = idf.cos(k_title, p["tok"])
    cont = idf.cont(p["tok"], k_all)
    lot_cont = idf.cont(p["lot_tok"], k_all) if p["lot_tok"] else 0.0
    text = max(0.5 * cos + 0.5 * cont, 0.5 * cos + 0.5 * lot_cont * 0.9)
    water = _water(p["cpv_all"], p["relevance"])
    dt = _kpo_date(p["first_published_on"])
    val = _kpo_value(kpo_value, p["contracts"], p["est"])
    v = val["score"] if val["score"] is not None else 0.25
    base = 0.45 * text + 0.10 * water + 0.10 * dt + 0.35 * v
    rule = None
    rel = val.get("rel_diff")
    if val.get("exact") and (text >= 0.1 or water > 0):
        base, rule = max(base, 0.97), "kwota zgodna co do grosza"
    elif rel is not None and not val.get("from_estimate") and text >= 0.8 and rel <= 0.05:
        base, rule = max(base, 0.92), "zgodny tytuł i kwota w granicach 5%"
    elif rel is not None and not val.get("from_estimate") and text >= 0.95 and rel <= 0.25 and dt == 1.0:
        # KPO total also covers design/supervision, so a near-identical title in the KPO era is enough
        base, rule = max(base, 0.90), "tytuł niemal identyczny, kwota w granicach 25%"
    elif rel is not None and text >= 0.5 and rel <= 0.05 or text >= 0.8 and rel is not None and rel <= 0.2:
        base, rule = max(base, 0.75), "zgodny tytuł lub kwota, do przeglądu"
    if p["cancelled"] and not p["contracts"]:
        base *= 0.9
    score = round(min(1.0, base * buyer_score), 3)
    shared = sorted(k_all & (p["tok"] | p["lot_tok"]), key=lambda t: -idf.w(t))
    return score, {"text": round(text, 3), "title_cos": round(cos, 3), "title_in_kpo_text": round(cont, 3),
                   "lots_in_kpo_text": round(lot_cont, 3), "shared_tokens": shared[:10], "water": water,
                   "water_basis": p["relevance"], "date_score": dt,
                   "first_published": p["first_published_on"].isoformat() if p["first_published_on"] else None,
                   "value": val, "rule": rule, "buyer_score": buyer_score, "cancelled": p["cancelled"],
                   "n_contracts": len(p["contracts"]), "title": (p["title"] or "")[:200]}


def _kpo_expl(f: dict, buyer: dict) -> str:
    val = f["value"]
    if val.get("score") is None:
        vtxt = "brak kwot do porównania"
    elif val["exact"]:
        vtxt = f"kwota KPO równa kwocie z BZP co do grosza ({val['basis']})"
    else:
        vtxt = f"najbliższa kwota z BZP: {val['basis']} {_pln(val['bzp_amount'])}, różnica {_pct(val['rel_diff'])}"
    parts = [f"Beneficjent jako zamawiający {buyer['name']} (NIP {buyer['nip'] or 'brak'}): {buyer['how']}",
             f"wspólne rdzenie słów: {', '.join(f['shared_tokens'][:6]) or 'brak'} (zgodność tekstu {_dec(f['text'])})",
             f"wod-kan: {'tak' if f['water'] >= 0.6 else 'częściowo' if f['water'] > 0 else 'nie'}",
             f"pierwsze ogłoszenie {f['first_published'] or 'brak daty'}", vtxt]
    if f["rule"]:
        parts.append(f"reguła: {f['rule']}")
    if f["cancelled"] and not f["n_contracts"]:
        parts.append("postępowanie unieważnione")
    return "; ".join(parts)


async def link_kpo(conn) -> tuple[list[tuple], dict]:
    kpo = await conn.fetch("""SELECT id, external_id, title, text, buyer_name, teryt, province, value_amount, data
                              FROM external_record WHERE source_kind = 'mapa_dotacji' AND kind = 'kpo_project'
                              ORDER BY id""")
    skipped = [r["id"] for r in kpo if "aggregate_or_programme_entry" in ((r["data"] or {}).get("flags") or [])]
    kpo = [r for r in kpo if r["id"] not in skipped]
    ter = await _teryt(conn)
    buyers = await _buyers(conn)
    by_prov: dict[str, list[Buyer]] = defaultdict(list)
    for b in buyers.values():
        for p in b.provinces:
            by_prov[p].append(b)
    all_b = list(buyers.values())

    resolved = {r["id"]: resolve_beneficiary(r, by_prov, all_b, ter) for r in kpo}
    keys = {b["key"] for res, _ in resolved.values() for b in res}
    procs = [dict(r) for r in await conn.fetch("""
        SELECT id, ocid, buyer_nip, buyer_name, province, title, cpv_all, relevance, first_published_on, cancelled,
               estimated_value_amount::float8 est
        FROM procedure WHERE sector = 'wod-kan' AND first_published_on >= $1""", KPO_SINCE)]
    idf = Idf([tok(p["title"]) for p in procs])
    for p in procs:
        p["bkey"] = buyer_key(p["buyer_nip"], p["buyer_name"], p["province"])
    procs = [p for p in procs if p["bkey"] in keys]
    pids = [p["id"] for p in procs]
    contracts, lots = defaultdict(list), defaultdict(list)
    for r in await conn.fetch("""
            SELECT c.procedure_id, c.lot_no, c.value_amount::float8 v,
                   max(pf.total_paid_amount)::float8 paid
            FROM contract c LEFT JOIN contract_performance pf ON pf.contract_id = c.id AND NOT pf.is_duplicate
            WHERE c.procedure_id = ANY($1::bigint[]) GROUP BY c.id""", pids):
        contracts[r["procedure_id"]].append({"lot": r["lot_no"], "value": r["v"], "paid": r["paid"]})
    for r in await conn.fetch("SELECT procedure_id, left(description, 300) d FROM lot WHERE procedure_id = ANY($1::bigint[])"
                              " AND lot_no > 0", pids):
        lots[r["procedure_id"]].append(r["d"] or "")
    by_key = defaultdict(list)
    for p in procs:
        p["tok"] = tok(p["title"])
        p["lot_tok"] = set().union(*(tok(d) for d in lots[p["id"]])) if lots[p["id"]] else set()
        p["contracts"] = contracts[p["id"]]
        by_key[p["bkey"]].append(p)

    rows, per = [], {}
    stats = Counter()
    for r in kpo:
        res, geo = resolved[r["id"]]
        stats["kpo_projects"] += 1
        if not res:
            stats["beneficiary_unresolved"] += 1
            per[r["id"]] = {"buyers": [], "geo": geo, "cands": []}
            continue
        stats["beneficiary_resolved"] += 1
        k_title = tok(r["title"])
        k_all = k_title | tok(r["text"])
        kv = float(r["value_amount"]) if r["value_amount"] is not None else None
        cands = []
        for b in res:
            for p in by_key.get(b["key"], []):
                s, f = score_kpo(k_title, k_all, p, idf, kv, b["score"])
                f["buyer"] = {k: b[k] for k in ("nip", "key", "name", "how", "score")}
                f["beneficiary_ambiguous"] = bool(geo.get("ambiguous"))
                f["kpo_value"] = kv
                cands.append((s, p, f, b))
        if not cands:
            stats["buyer_without_procedures"] += 1
        cands.sort(key=lambda c: (-c[0], c[1]["id"]))
        top = [c for c in cands if c[0] >= KPO_MIN_KEEP][:TOP_N]
        if (len(top) > 1 and top[0][0] >= ACCEPT and not top[0][2]["value"].get("exact")
                and (top[1][0] >= top[0][0] - 0.03
                     or top[1][2]["text"] >= 0.95 and top[0][2]["text"] >= 0.95 and top[1][2]["n_contracts"]
                     and top[1][0] >= 0.75)):
            # two near-equal strong candidates, or twin titles that both led to contracts (stages): expert decides
            top[0] = (min(top[0][0], 0.89), *top[0][1:])
            top[0][2]["ambiguous_top"] = True
        per[r["id"]] = {"buyers": res, "geo": geo, "cands": [(c[0], c[1]["id"]) for c in top]}
        for rank, (s, p, f, b) in enumerate(top, 1):
            dec = "accept" if s >= ACCEPT else "review" if s >= REVIEW else "reject"
            expl = _kpo_expl(f, b)
            if f.get("ambiguous_top"):
                expl += "; drugi kandydat z podobnym wynikiem, decyzja eksperta"
            if geo.get("ambiguous"):
                expl += "; nazwa beneficjenta pasuje do kilku zamawiających"
            f["geo"] = geo
            rows.append(("external_record", r["id"], "procedure", p["id"], p["ocid"], KPO_METHOD, f, s, rank, expl, dec))
    stats["procedures_considered"] = len(procs)
    return rows, {"stats": dict(stats), "per": per, "skipped_aggregate": skipped}


# ======================================================================================
# 2. CRU agreements -> contracts
# ======================================================================================

def _cru_value(cru: float | None, bzp: float | None) -> dict:
    if not cru or not bzp:
        return {"score": None}
    best = None
    for f, label in ((1.0, "ta sama podstawa"), (VAT, "CRU netto x 1,23"), (1 / VAT, "CRU brutto / 1,23")):
        d = abs(cru * f - bzp)
        r = d / bzp
        exact = d <= (0.01 if f == 1.0 else 1.0)
        cand = (0 if exact else 1, r, f, label, exact)
        if best is None or cand[:2] < best[:2]:
            best = cand
    _, r, f, label, exact = best
    if exact:
        s = 1.0 if f == 1.0 else 0.9
    elif r <= 0.01:
        s = 0.85 if f == 1.0 else 0.75
    elif r <= 0.05:
        s = 0.35
    else:
        s = 0.0
    return {"score": s, "rel_diff": round(r, 4), "factor": round(f, 4), "basis": label, "exact": exact}


def _cru_date(days: int) -> float:
    return next(v for lim, v in ((0, 1.0), (3, 0.9), (14, 0.7), (30, 0.45), (45, 0.25), (10 ** 6, 0.0)) if days <= lim)


def score_cru(a: dict, c: dict, idf: Idf) -> tuple[float, dict]:
    days = abs((a["signed"] - c["signed_on"]).days)
    d = _cru_date(days)
    val = _cru_value(a["value"], c["value"])
    v = val["score"] or 0.0
    a_nips, c_nip = a["contractor_nips"], c["contractor_nip"]
    if c_nip and c_nip in a_nips:
        ctr, cs = "nip", 1.0
    elif a["contractor_names"] and c["contractor_name"] and max(
            fuzz.token_sort_ratio(norm_org(c["contractor_name"]), n) for n in a["contractor_names"]) >= 90:
        ctr, cs = "name", 0.8
    elif (a_nips or a["contractor_names"]) and (c_nip or c["contractor_name"]):
        ctr, cs = "mismatch", 0.0
    else:
        ctr, cs = "unknown", 0.5
    text = max(idf.cos(a["tok"], c["tok"]), idf.cos(a["tok"], c["tok"] | c["lot_tok"]))
    combined = 0.40 * v + 0.25 * text + 0.20 * d + 0.15 * cs
    near = val["score"] is not None and val["rel_diff"] <= 0.01
    if ctr in ("nip", "name") and near:
        tier, score = "A", 0.90 + 0.10 * (v + d + text) / 3
    elif ctr == "unknown" and val.get("exact") and days <= 14 and text >= 0.2:
        tier, score = "A", 0.90 + 0.05 * (d + text) / 2
    elif (ctr in ("nip", "name") and (text >= 0.5 or val["score"] is not None and val["rel_diff"] <= 0.05)
          or near and (ctr == "unknown" and text >= 0.2 or ctr == "mismatch" and text >= 0.4)):
        # a round amount alone (e.g. 238 000,00) is weak: it needs the same contractor or a shared subject
        tier, score = "B", 0.60 + 0.29 * combined
    else:
        tier, score = "C", 0.59 * combined
    return round(score, 3), {"tier": tier, "combined": round(combined, 3), "days_apart": days, "date_score": d,
                             "value": val, "contractor": ctr, "text": round(text, 3),
                             "shared_tokens": sorted(a["tok"] & (c["tok"] | c["lot_tok"]), key=lambda t: -idf.w(t))[:8],
                             "bzp_signed_on": c["signed_on"].isoformat(), "cru_signed_on": a["signed"].isoformat(),
                             "bzp_value": c["value"], "cru_value": a["value"], "lot_no": c["lot_no"],
                             "sector": c["sector"], "ocid": c["ocid"], "contractor_bzp": c["contractor_name"]}


def _cru_expl(f: dict, a: dict) -> str:
    val = f["value"]
    ctr = {"nip": "wykonawca zgodny (NIP)", "name": "wykonawca zgodny (nazwa)", "mismatch": "inny wykonawca",
           "unknown": "brak danych o wykonawcy w CRU"}[f["contractor"]]
    if val.get("score") is None:
        vtxt = "brak kwoty do porównania"
    elif val["exact"]:
        vtxt = f"wartość zgodna ({val['basis']})"
    else:
        vtxt = f"różnica wartości {_pct(val['rel_diff'])} ({val['basis']})"
    who = "NIP zamawiającego" if a["buyer_via"] == "nip" else "REGON zamawiającego (NIP z BZP)"
    days = "ta sama data zawarcia" if not f["days_apart"] else f"daty zawarcia różnią się o {f['days_apart']} dni"
    return (f"{who} zgodny; {ctr}; {vtxt}; {days}; wspólne rdzenie słów przedmiotu: "
            f"{', '.join(f['shared_tokens'][:6]) or 'brak'}")


async def _regon_map(conn, cru: list) -> dict[str, set[str]]:
    m: dict[str, set[str]] = defaultdict(set)
    async with conn.transaction():
        await conn.execute("SET LOCAL max_parallel_workers_per_gather = 0")
        rows = await conn.fetch("""SELECT DISTINCT buyer_nip, substring(parsed_fields->>'1.4' from '[0-9]{9,14}') regon
                                   FROM notice WHERE buyer_nip IS NOT NULL AND parsed_fields->>'1.4' ILIKE '%regon%'""")
    for r in rows:
        if r["regon"]:
            m[r["regon"][:9]].add(r["buyer_nip"])
    for r in await conn.fetch("SELECT nip, regon FROM organization WHERE regon IS NOT NULL AND nip IS NOT NULL"):
        m[ids.digits(r["regon"])[:9]].add(r["nip"])
    for r in cru:
        if r["buyer_nip"] and r["buyer_regon"]:
            m[ids.digits(r["buyer_regon"])[:9]].add(ids.digits(r["buyer_nip"]))
    return m


async def link_cru(conn) -> tuple[list[tuple], dict]:
    cru = await conn.fetch("""
        SELECT id, title, published_on, buyer_nip, buyer_regon, buyer_name, value_amount::float8 v,
               coalesce(data->'contractors', '[]'::jsonb) contractors, data->>'signed_on' signed_on,
               coalesce((data->>'n_changes')::int, 0) n_changes,
               (SELECT array_agg(DISTINCT trim(coalesce(ch->>'code', '') || ' ' || coalesce(ch->>'type', '')))
                FROM jsonb_array_elements(coalesce(data->'changes', '[]'::jsonb)) ch) codes,
               data->>'water_relevant' = 'true' water, data->>'detail_fetched' = 'true' detail
        FROM external_record WHERE source_kind = 'cru' AND kind = 'cru_agreement' ORDER BY id""")
    regon = await _regon_map(conn, cru)
    stats = Counter()
    agreements = []
    for r in cru:
        stats["cru_agreements"] += 1
        signed = ids_date(r["signed_on"]) or r["published_on"]
        nip, via = ids.digits(r["buyer_nip"]) or None, "nip"
        if not nip and r["buyer_regon"]:
            hit = regon.get(ids.digits(r["buyer_regon"])[:9], set())
            if len(hit) == 1:
                nip, via = next(iter(hit)), "regon"
            elif len(hit) > 1:
                stats["buyer_regon_ambiguous"] += 1
        if not nip:
            stats["buyer_unresolved"] += 1
            continue
        stats[f"buyer_via_{via}"] += 1
        if signed is None:
            stats["no_signed_date"] += 1
            continue
        ctrs = r["contractors"] or []
        agreements.append({"id": r["id"], "nip": nip, "buyer_via": via, "signed": signed, "value": r["v"],
                           "title": r["title"], "tok": tok(r["title"]), "n_changes": r["n_changes"],
                           "codes": list(r["codes"] or []), "water": r["water"], "detail": r["detail"],
                           "contractor_nips": {ids.digits(c.get("nip")) for c in ctrs if ids.digits(c.get("nip"))},
                           "contractor_names": [norm_org(c.get("name")) for c in ctrs if c.get("name")]})
    if not agreements:
        return [], {"stats": dict(stats), "agreements": {}}
    since = min(a["signed"] for a in agreements) - timedelta(days=CRU_WINDOW)
    async with conn.transaction():
        await conn.execute("SET LOCAL max_parallel_workers_per_gather = 0")   # docker /dev/shm is 64 MB
        crows = await conn.fetch("""
            SELECT c.id, c.key, c.lot_no, c.contractor_nip, c.contractor_name, c.signed_on, c.value_amount::float8 v,
                   pr.buyer_nip, pr.title, pr.ocid, pr.sector, left(l.description, 300) lot_desc
            FROM contract c JOIN procedure pr ON pr.id = c.procedure_id LEFT JOIN lot l ON l.id = c.lot_id
            WHERE c.signed_on >= $1 AND pr.buyer_nip IS NOT NULL""", since)
    titles = {}
    by_nip = defaultdict(list)
    for c in crows:
        t = titles.setdefault(c["ocid"], tok(c["title"]))
        by_nip[c["buyer_nip"]].append({"id": c["id"], "key": c["key"] or f"contract:{c['id']}", "lot_no": c["lot_no"],
                                       "contractor_nip": ids.digits(c["contractor_nip"]) or None,
                                       "contractor_name": c["contractor_name"], "signed_on": c["signed_on"],
                                       "value": c["v"], "ocid": c["ocid"], "sector": c["sector"], "tok": t,
                                       "lot_tok": tok(c["lot_desc"]) if c["lot_desc"] else set()})
    idf = Idf(list(titles.values()) + [a["tok"] for a in agreements])
    stats["bzp_contracts_in_window"] = len(crows)
    rows = []
    for a in agreements:
        pool = [c for c in by_nip.get(a["nip"], []) if abs((a["signed"] - c["signed_on"]).days) <= CRU_WINDOW]
        if not by_nip.get(a["nip"]):
            stats["buyer_without_bzp_contracts"] += 1
            continue
        if not pool:
            stats["no_contract_in_date_window"] += 1
            continue
        stats["with_candidates_in_window"] += 1
        cands = sorted(((*score_cru(a, c, idf), c) for c in pool), key=lambda x: (-x[0], x[2]["id"]))
        top = [x for x in cands if x[0] >= CRU_MIN_KEEP][:TOP_N]
        for rank, (s, f, c) in enumerate(top, 1):
            rows.append([a, c, s, f, rank])
    # one contract <-> one agreement: only the best agreement keeps an automatic accept
    acc = defaultdict(list)
    for row in rows:
        if row[2] >= ACCEPT:
            acc[row[1]["id"]].append(row)
    for group in acc.values():
        group.sort(key=lambda x: -x[2])
        for row in group[1:]:
            row[3]["demoted"] = "ta sama umowa BZP ma lepiej dopasowaną umowę CRU"
            row[2] = min(row[2], 0.89)
    per_agreement = defaultdict(list)
    for row in rows:
        per_agreement[row[0]["id"]].append(row)
    for group in per_agreement.values():
        strong = [x for x in group if x[2] >= ACCEPT]
        for row in strong[1:]:
            row[3]["demoted"] = "kilka umów BZP pasuje równie dobrze (np. części z tą samą kwotą)"
            row[2] = min(row[2], 0.89)
    out = []
    for a, c, s, f, rank in rows:
        dec = "accept" if s >= ACCEPT else "review" if s >= REVIEW else "reject"
        expl = _cru_expl(f, a) + (f"; {f['demoted']}" if f.get("demoted") else "")
        f.update({"buyer_nip": a["nip"], "buyer_via": a["buyer_via"], "cru_n_changes": a["n_changes"],
                  "cru_changes": a["codes"], "cru_detail_fetched": a["detail"]})
        out.append(("external_record", a["id"], "contract", c["id"], c["key"], CRU_METHOD, f, round(s, 3), rank, expl,
                    dec))
    return out, {"stats": dict(stats), "agreements": {a["id"]: a for a in agreements}}


def ids_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


# ======================================================================================
# Reference check (pilot pairs, used only after scoring)
# ======================================================================================

async def _reference(conn) -> list[dict]:
    return [dict(r) for r in await conn.fetch("""
        SELECT DISTINCT ON (p.rm_id) p.rm_id, p.beneficiary_nip, lc.right_id AS kpo_id, pp.procedure_id, pr.ocid
        FROM link_candidate lc JOIN project p ON p.id = lc.left_id
        JOIN project_procedure pp ON pp.project_id = p.id AND pp.method <> 'cross_reference_related'
        JOIN procedure pr ON pr.id = pp.procedure_id
        WHERE lc.left_table = 'project' AND lc.right_table = 'external_record' AND lc.method = 'exact_value+beneficiary'
          AND lc.right_id IS NOT NULL AND lc.review_status <> 'rejected'
        ORDER BY p.rm_id, pp.score DESC NULLS LAST""")]


def reference_check(ref: list[dict], kpo_meta: dict, rows: list[tuple]) -> dict:
    cands = defaultdict(list)
    for r in rows:
        if r[5] == KPO_METHOD:
            cands[r[1]].append(r)
    out = {"pairs": len(ref), "beneficiary_found": 0, "beneficiary_top1": 0, "top1_correct": 0, "in_top3": 0,
           "accepted": 0, "accepted_correct": 0, "correct_accepted": 0, "per_pair": []}
    for x in ref:
        meta = kpo_meta["per"].get(x["kpo_id"], {"buyers": []})
        nips = [b["nip"] for b in meta["buyers"]]
        cs = sorted(cands.get(x["kpo_id"], []), key=lambda r: r[8])
        hit = next((r for r in cs if r[3] == x["procedure_id"]), None)
        out["beneficiary_found"] += x["beneficiary_nip"] in nips
        out["beneficiary_top1"] += bool(nips) and nips[0] == x["beneficiary_nip"]
        out["top1_correct"] += bool(cs) and cs[0][3] == x["procedure_id"]
        out["in_top3"] += hit is not None
        acc = [r for r in cs if r[10] == "accept"]
        out["accepted"] += len(acc)
        out["accepted_correct"] += sum(1 for r in acc if r[3] == x["procedure_id"])
        out["correct_accepted"] += bool(hit) and hit[10] == "accept"
        out["per_pair"].append({"rm_id": x["rm_id"], "kpo_id": x["kpo_id"], "ocid": x["ocid"],
                                "beneficiary_ok": x["beneficiary_nip"] in nips, "rank": hit[8] if hit else None,
                                "score": hit[7] if hit else None, "decision": hit[10] if hit else None,
                                "top1_ocid": cs[0][4] if cs else None, "top1_score": cs[0][7] if cs else None})
    n = out["pairs"] or 1
    out["precision_at_1"] = round(out["top1_correct"] / n, 3)
    out["recall_at_3"] = round(out["in_top3"] / n, 3)
    out["precision_accepted"] = round(out["accepted_correct"] / out["accepted"], 3) if out["accepted"] else None
    out["recall_accepted"] = round(out["correct_accepted"] / n, 3)
    return out


# ======================================================================================
# Stage
# ======================================================================================

COLS = ("left_table", "left_id", "right_table", "right_id", "right_ref", "method", "features", "score", "rank",
        "explanation", "decision", "review_status", "run_id", "reference_verdict")
KEY = ("left_table", "left_id", "right_table", "right_ref", "method")


async def run(conn, rid) -> dict:
    kpo_rows, kpo_meta = await link_kpo(conn)
    cru_rows, cru_meta = await link_cru(conn)
    ref = await _reference(conn)
    refcheck = reference_check(ref, kpo_meta, kpo_rows)
    ref_by_kpo = {x["kpo_id"]: x["procedure_id"] for x in ref}

    protected = {(r["left_table"], r["left_id"], r["right_table"], r["right_ref"], r["method"]) for r in await conn.fetch(
        "SELECT left_table, left_id, right_table, right_ref, method FROM link_candidate "
        "WHERE method = ANY($1::text[]) AND review_status = ANY($2::text[])", [KPO_METHOD, CRU_METHOD],
        list(PROTECTED_STATUS))}
    recs = []
    for r in kpo_rows + cru_rows:
        if (r[0], r[1], r[2], r[4], r[5]) in protected:
            continue
        verdict = None
        if r[5] == KPO_METHOD and r[1] in ref_by_kpo:
            verdict = "correct" if r[3] == ref_by_kpo[r[1]] else "wrong" if r[8] == 1 else "uncertain"
        recs.append((*r, "auto" if r[10] == "accept" else "proposed", rid, verdict))
    async with conn.transaction():
        await upsert_copy(conn, "link_candidate", COLS, recs, KEY,
                          update=["right_id", "features", "score", "rank", "explanation", "decision", "review_status",
                                  "run_id", "reference_verdict"])
        res = await conn.execute(
            "DELETE FROM link_candidate WHERE method = ANY($1::text[]) AND left_table = 'external_record' "
            "AND run_id IS DISTINCT FROM $2 AND NOT (review_status = ANY($3::text[]))",
            [KPO_METHOD, CRU_METHOD], rid, list(PROTECTED_STATUS))
        stale = int(res.split()[-1])
        stats = _stats(kpo_rows, kpo_meta, cru_rows, cru_meta, refcheck)
        stats["skipped_expert_rows"] = len(protected)
        stats["stale_removed"] = stale
        stats["changes_linked_bzp_change_notice"] = await _cru_changes_with_bzp(conn, cru_rows, cru_meta)
        stats["report_pl"] = report_pl(stats)
        await audit(conn, "system:linker", "link_national", "link_candidate", None, None,
                    {k: stats[k] for k in ("kpo", "cru", "reference")})
    return stats


async def _cru_changes_with_bzp(conn, cru_rows, cru_meta) -> int:
    """CRU agreements with annexes linked (accept) to a BZP contract that ALSO has a BZP change notice."""
    cids = [r[3] for r in cru_rows if r[10] == "accept" and cru_meta["agreements"][r[1]]["n_changes"] > 0]
    if not cids:
        return 0
    return await conn.fetchval("SELECT count(DISTINCT contract_id) FROM contract_change WHERE contract_id = ANY($1::bigint[])",
                               cids)


def _stats(kpo_rows, kpo_meta, cru_rows, cru_meta, refcheck) -> dict:
    k_top = [r for r in kpo_rows if r[8] == 1]
    kpo = {**kpo_meta["stats"], "skipped_aggregate": len(kpo_meta["skipped_aggregate"]),
           "candidates": len(kpo_rows), "by_decision": _count(r[10] for r in kpo_rows),
           "top1_by_decision": _count(r[10] for r in k_top),
           "top1_exact_value": sum(1 for r in k_top if r[6]["value"].get("exact")),
           "projects_with_candidate": len(k_top),
           "beneficiary_how": _count(m["buyers"][0]["how"].split(" (")[0].split(",")[0]
                                     for m in kpo_meta["per"].values() if m["buyers"])}
    c_top = [r for r in cru_rows if r[8] == 1]
    ag = cru_meta["agreements"]
    with_changes = {i for i, a in ag.items() if a["n_changes"] > 0}
    top_dec = {r[1]: r[10] for r in c_top}
    codes: dict[str, Counter] = defaultdict(Counter)     # change type -> {accept, review, all}
    for i in with_changes:
        for code in set(ag[i]["codes"]):
            codes[code]["all"] += 1
            if top_dec.get(i) in ("accept", "review"):
                codes[code][top_dec[i]] += 1
    cru = {**cru_meta["stats"], "candidates": len(cru_rows), "by_decision": _count(r[10] for r in cru_rows),
           "top1_by_decision": _count(r[10] for r in c_top),
           "top1_by_contractor": _count(r[6]["contractor"] for r in c_top),
           "accepted_by_sector": _count(r[6]["sector"] for r in c_top if r[10] == "accept"),
           # which VAT basis made the CRU value meet the (gross) BZP contract value: evidence for value_vat
           "accepted_value_basis": _count(r[6]["value"].get("basis") for r in c_top if r[10] == "accept"),
           "with_changes": len(with_changes),
           "with_changes_accept": sum(1 for i in with_changes if top_dec.get(i) == "accept"),
           "with_changes_review": sum(1 for i in with_changes if top_dec.get(i) == "review"),
           "with_changes_by_type": {k: dict(v) for k, v in sorted(codes.items(), key=lambda kv: -kv[1]["all"])}}
    by_method = {KPO_METHOD: _count(r[10] for r in kpo_rows), CRU_METHOD: _count(r[10] for r in cru_rows)}
    return {"candidates_by_method": by_method, "kpo": kpo, "cru": cru, "reference": refcheck}


def report_pl(s: dict) -> str:
    """Section for the test report (Polish; no em dashes or middle dots, house style)."""
    k, c, r = s["kpo"], s["cru"], s["reference"]
    kd, cd = k["top1_by_decision"], c["top1_by_decision"]
    pa = r["precision_accepted"]
    basis = c.get("accepted_value_basis") or {}
    tsu02 = next((v for t, v in (c.get("with_changes_by_type") or {}).items() if t.startswith("TSU02")), None)
    annex = (f" (aneksy TSU02: {tsu02.get('all', 0)}, powiązane automatycznie {tsu02.get('accept', 0)}, do przeglądu "
             f"{tsu02.get('review', 0)})") if tsu02 else ""
    n_acc = sum(basis.values()) or 1
    kpo = (
        f"**Projekty KPO B3.1.1 (Mapa Dotacji) a postępowania BZP.** Rekordów: {k['kpo_projects']} (pominięto "
        f"{k['skipped_aggregate']} wpis zbiorczy programu). Mapa Dotacji nie podaje numeru KPO ani NIP, więc beneficjenta "
        "przypisujemy do zamawiającego z BZP po nazwie gminy, jej rodzaju z TERYT (miejska, wiejska, miejsko-wiejska) i "
        "województwie, a spółki komunalne po podobnej nazwie i siedzibie w powiecie. Beneficjent rozpoznany: "
        f"{k['beneficiary_resolved']}, nierozpoznany: {k['beneficiary_unresolved']} (głównie spółki, które nie ogłaszają "
        f"zamówień w BZP). Projekty z kandydatem: {k['projects_with_candidate']}. Najlepszy kandydat: akceptacja "
        f"automatyczna {kd.get('accept', 0)}, do przeglądu {kd.get('review', 0)}, odrzucony {kd.get('reject', 0)}; "
        f"kwota KPO równa kwocie z BZP co do grosza: {k['top1_exact_value']}. Zapisano {k['candidates']} kandydatów "
        "(do 3 na projekt), każdy z cechami i uzasadnieniem.")
    ref = (
        f"**Kontrola na parach referencyjnych.** {r['pairs']} projektów pilotażowych z numerem KPO ma znany rekord Mapy "
        "Dotacji i postępowanie BZP (etap `link_pilot`). Pary nie są cechą wejściową, służą wyłącznie do oceny. "
        f"Beneficjent przypisany do właściwego NIP: {r['beneficiary_found']}/{r['pairs']}. Właściwe postępowanie na "
        f"1. miejscu: {r['top1_correct']}/{r['pairs']} (precyzja@1 {_pct(r['precision_at_1'])}), w pierwszej trójce: "
        f"{r['in_top3']}/{r['pairs']} (czułość@3 {_pct(r['recall_at_3'])}). Akceptacje automatyczne dla tych projektów: "
        f"{r['accepted']}, w tym poprawne {r['accepted_correct']}"
        + (f" (precyzja {_pct(pa)})" if pa is not None else "")
        + f"; właściwe postępowanie w kolejce do przeglądu eksperta: {r['pairs'] - r['correct_accepted']}.")
    cru = (
        f"**Umowy z Centralnego Rejestru Umów (od 1.07.2026) a umowy z BZP.** Umów CRU: {c['cru_agreements']}. "
        f"Zamawiający rozpoznany po NIP: {c.get('buyer_via_nip', 0)}, po numerze REGON z ogłoszeń BZP: "
        f"{c.get('buyer_via_regon', 0)}, nierozpoznany: {c.get('buyer_unresolved', 0)}. Dla "
        f"{c.get('with_candidates_in_window', 0)} umów CRU zamawiający ma w BZP umowę zawartą w oknie ±{CRU_WINDOW} dni "
        "(większość pozostałych to umowy poniżej progu stosowania ustawy). Najlepszy kandydat: akceptacja automatyczna "
        f"{cd.get('accept', 0)}, do przeglądu {cd.get('review', 0)}, odrzucony {cd.get('reject', 0)}. Wartość z CRU "
        f"zgadza się z wartością brutto z BZP po doliczeniu 23% VAT w {_pct(basis.get('CRU netto x 1,23', 0) / n_acc)} "
        "zaakceptowanych par, czyli CRU podaje zwykle kwoty netto. Umowy CRU z aneksami lub innymi zmianami: "
        f"{c['with_changes']}, z czego powiązane z umową z BZP automatycznie {c['with_changes_accept']} i do przeglądu "
        f"{c['with_changes_review']}{annex}. Spośród zaakceptowanych ogłoszenie o zmianie umowy w BZP ma tylko: "
        f"{s.get('changes_linked_bzp_change_notice', 0)}, więc CRU uzupełnia moduł monitorowania o zmiany niewidoczne "
        "w BZP.")
    rules = ("Progi: akceptacja automatyczna od 0,90 (nadal podlega przeglądowi eksperta), przegląd od 0,60 do 0,90, "
             "odrzucenie poniżej 0,60. Wiersze zatwierdzone, poprawione lub odrzucone przez eksperta nie są nadpisywane.")
    return f"### Powiązania krajowe (etap `link_national`)\n\n{kpo}\n\n{ref}\n\n{cru}\n\n{rules}"
