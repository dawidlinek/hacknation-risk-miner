"""
wodkan_classify.py - relevance filter + subsector / work-type / delivery-model tagging for
water & sewage (wod-kan) procurement notices. Pure stdlib, rule based, explainable
(each decision returns the matched keyword so the UI / expert panel can show "why").

Subsectors (expert material 03, section 2.1):
  WOD  Sieć wodociągowa
  SAN  Kanalizacja sanitarna
  OCZ  Oczyszczalnia ścieków
  SUW  Uzdatnianie i zaopatrzenie w wodę
  DESZ Kanalizacja deszczowa i retencja
  INNE Inne obiekty wod-kan

Rules (applied to the title first, then the short description if the title is vague):
 1. Find all wod-kan object keywords and all "other primary object" keywords (roads, buildings,
    schools, sports, heating, gas, river/flood works, internal plumbing...) with positions.
 2. The FIRST object mentioned in the title is taken as the dominant scope (Polish titles put
    the main object first: "Przebudowa drogi ... wraz z kanalizacją deszczową" -> road).
    - wod-kan first  -> relevance 'core'
    - other first but wod-kan also present -> 'component' (wod-kan is a secondary scope)
    - no wod-kan keyword -> fall back to CPV main code (strong wod-kan CPV -> 'cpv_only'),
      else 'none'.
 3. Primary subsector = subsector of the first wod-kan keyword; all matched subsectors are
    returned as `subsectors` (main + additional, as the expert classification requires).
 4. Service-type scopes (design only, supervision, maintenance/emergency repairs, deliveries)
    are tagged in `scope_kind` so they can be excluded from an investment reference class.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SUBSECTOR_NAMES = {
    "WOD": "Sieć wodociągowa",
    "SAN": "Kanalizacja sanitarna",
    "OCZ": "Oczyszczalnia ścieków",
    "SUW": "Uzdatnianie i zaopatrzenie w wodę",
    "DESZ": "Kanalizacja deszczowa i retencja",
    "INNE": "Inne obiekty wod-kan",
}

# order matters inside a position tie: more specific first
_SUB_PATTERNS: list[tuple[str, str]] = [
    ("OCZ", r"(?:pod)?oczyszczal\w*|przydomow\w+\s+oczyszcz\w*|osad\w*\s+ściekow\w*|stacj\w+\s+zlewn\w*|punkt\w*\s+zlewn\w*|\bpoś\b"),
    ("SUW", r"uzdatnia\w*|\bsuw\b|stacj\w+\s+wodociągow\w*|ujęci\w+\s+wod\w*|ujęci\w+|studni\w*\s+(?:głębinow|wiercon|publiczn)\w*|"
            r"hydrofor\w*|(?:stacj\w+|komor\w+|pompowni\w*)\s+(?:podnoszenia|podwyższania|regulacji)\s+ciśnienia|zbiornik\w*\s+(?:wody\s+pitnej|wyrównawcz\w*|wody\s+czystej|terenow\w*)|wież\w+\s+ciśnień|"
            r"(?:prze)?pompowni\w*\s+wody|zakład\w*\s+(?:produkcji|uzdatniania)\s+wody|zaopatrzeni\w+\s+(?:w\s+wodę|ludności)|wody\s+pitnej"),
    ("DESZ", r"kanalizac\w*\s+(?:deszczow|burzow|opadow)\w*|deszczów\w*|deszczow\w*|burzow\w*|wód\s+opadowych|wody\s+opadow\w*|"
             r"opadow\w*|retencj\w*|retencyjn\w*|odwodnieni\w*|odwadniaj\w*|drenaż\w*|wpust\w*\s+uliczn\w*|separator\w*|"
             r"wylot\w*\s+(?:do|kanalizacji)|zagospodarowani\w+\s+wód"),
    ("SAN", r"kanalizac(?!\w*\s+(?:teletechn|kablow|telekom|światłow|energ))\w*|kanał\w*\s+sanitarn\w*|rekanalizac\w*|kolektor(?!\w*\s+słone)\w*|(?:prze)?pompowni\w*\s+ściek\w*|tłoczn\w*|ściek\w*|"
            r"sanitarn\w*\s+(?:grawitacyjn|ciśnieniow)\w*|wodno[\s-]*ściekow\w*"),
    ("WOD", r"wodociąg\w*|sieci\s+wod(?:y|n\w*)\b|sieć\s+wodn\w*|magistral\w*\s+wod\w*|przyłącz\w*\s+wod\w*|wodno[\s-]*kanaliz\w*|"
            r"wod[\s.-]*kan\b|wod\.?\s*-\s*kan\w*|rurociąg\w*\s+(?:wody|tranzytow|przesyłow)\w*|hydrant\w*|sieci\s+wodno"),
]
_SUB_RX = [(k, re.compile(r"\b(?:" + p + ")", re.I)) for k, p in _SUB_PATTERNS]

# keywords that make a wod-kan mention part of something else (dominant other object)
_OTHER = re.compile(
    r"\b(?:drog\w*|\bdróg\b|\bulic\w*|\bul\.|chodnik\w*|nawierzchn\w*|parking\w*|ścieżk\w*|ciąg\w*\s+pieszo|\bmost\w*|wiadukt\w*|"
    r"skrzyżowa\w*|rond\w*|zatok\w*|budyn\w*|budynk\w*|szkoł\w*|szkol\w*|przedszkol\w*|żłob\w*|sal\w*\s+gimnastyczn\w*|boisk\w*|"
    r"hal\w*\s+sportow\w*|basen\w*|pływal\w*|termomoderniz\w*|świetlic\w*|remiz\w*|strażnic\w*|ośrod\w*|szpital\w*|przychodn\w*|"
    r"dom\w*\s+kultury|plac\w*\s+zabaw|rynk\w*|rewitaliz\w*|cmentarz\w*|oświetleni\w*|gazociąg\w*|gazow\w*|ciepłownicz\w*|"
    r"kotłown\w*|instalac\w*\s+(?:wewn\w*|c\.?\s*o\.?|centralnego|wod\w*|kanaliz\w*|sanitarn\w*|hydrant\w*)|łazien\w*|toalet\w*|"
    r"sanitariat\w*|melioracj\w*|\brzek\w*|\brzece\b|potok\w*|ciek\w*|wał\w*\s+przeciwpow\w*|przeciwpowodziow\w*|jaz(?:u|em|y|ów)?\b|"
    r"kanał\w*\s+(?!sanitarn|ściek|deszcz|burz|tłoczn)\w+|zbiornik\w*\s+wodn\w*|staw\w*|kąpielisk\w*|tężni\w*|fontann\w*|"
    r"mieszka\w*|lokal\w*|kamienic\w*|obiekt\w*\s+sportow\w*|stadion\w*|amfiteatr\w*|park\w*\b|zieleni\w*|przystan\w*|dworc\w*|"
    r"tor\w*\s+(?:kolej|tramwaj)\w*|tramwaj\w*|kolej\w*|lotnisk\w*|port\w*\b|nabrzeż\w*|komisariat\w*|jednost\w*\s+wojsk\w*|"
    r"koszar\w*|więzien\w*|zakład\w*\s+karn\w*|uczelni\w*|akademi\w*|uniwersytet\w*|muze\w*|teatr\w*|bibliotek\w*|kości\w*|"
    r"urz[ęą]d(?:u|zie|y|ów|em|ach)?\b|starostw\w*|ratusz\w*|hotel\w*|schronisk\w*|PSZOK|składowisk\w*|odpad\w*|fotowolt\w*|pomp\w*\s+ciepła|"
    r"pieszo[\s-]*rower\w*|rowerow\w*|placu|plac\w*\b|garaż\w*|magazyn\w*|wiat\w*|ogrodzeni\w*|elewac\w*|dach\w*|piwnic\w*|sieci\w*\s+ciepł\w*|kanaliz\w*\s+teletechn\w*|"
    r"teletechn\w*|światłowod\w*|energetyczn\w*|elektroenerget\w*)",
    re.I,
)
_STRONG_CPV = {
    "45231300", "45232410", "45232400", "45232440", "45232411", "45232150", "45232151", "45232100", "45232152",
    "45232153", "45232154", "45252127", "45232421", "45232420", "45232422", "45252100", "45252126", "45232430",
    "45252120", "45252121", "45252122", "45252130", "45252140", "45252200", "45252210", "45232423", "45232424",
    "45232431", "45232130", "45232454", "45262220", "45262200", "45255110", "45255600", "45259100",
}
_CPV_SUB = {
    "45231300": None, "45232410": "SAN", "45232400": "SAN", "45232440": "SAN", "45232411": "SAN", "45232423": "SAN",
    "45232424": "SAN", "45232431": "SAN", "45255600": "SAN", "45232150": "WOD", "45232100": "WOD", "45232151": "SUW",
    "45232152": "SUW", "45232153": "SUW", "45232154": "SUW", "45252127": "OCZ", "45232421": "OCZ", "45232420": "OCZ",
    "45232422": "OCZ", "45252100": "OCZ", "45252121": "OCZ", "45252122": "OCZ", "45252130": "OCZ", "45252140": "OCZ",
    "45252200": "OCZ", "45259100": "OCZ", "45252126": "SUW", "45232430": "SUW", "45252120": "SUW", "45252210": "SUW",
    "45262220": "SUW", "45262200": "SUW", "45255110": "SUW", "45232130": "DESZ", "45232454": "DESZ",
}

_DESIGN_BUILD = re.compile(
    r"zaprojektuj\w*\s+i\s+wybuduj|projektuj\s+i\s+buduj|zaprojektowani\w*\s+(?:i|oraz)\s+(?:wybudowani|budow|wykonani|realizac|"
    r"przebudow|rozbudow|modernizac)\w*|w\s+formule\s+(?:zaprojektuj|projektuj|„zaprojektuj|\"zaprojektuj)|"
    r"opracowani\w+\s+dokumentacji\s+projektowej\s+(?:oraz|i|wraz\s+z)\s+(?:wykonani|realizac|budow|przebudow|rozbudow|"
    r"wybudowani|robot)\w*|wraz\s+z\s+(?:opracowaniem|wykonaniem)\s+(?:dokumentacji|projektu)|zaprojektowanie\s+i\s+wykonanie|"
    r"\bpib\b|design\s*(?:&|and)\s*build",
    re.I,
)
_DESIGN_ONLY = re.compile(r"^\W*(?:opracowani\w+|wykonani\w+|sporządzeni\w+|aktualizac\w+)\s+(?:kompletnej\s+|wielobranżowej\s+)?"
                          r"(?:dokumentacj\w+|projekt\w+|koncepcj\w+|studium|program\w+\s+funkcjonaln)", re.I)
_SUPERVISION = re.compile(r"^\W*(?:pełnieni\w+|sprawowani\w+|świadczeni\w+)?\s*(?:funkcji\s+)?(?:nadz\w+|inspektor\w*|inżynier\w*\s+kontraktu)", re.I)
_MAINTENANCE = re.compile(
    r"usuwani\w+\s+awarii|awari\w+|bieżąc\w+\s+(?:utrzyman|konserwac|napraw|remont)\w*|konserwacj\w*|eksploatac\w*|utrzymani\w+|"
    r"czyszczeni\w*|udrażniani\w*|udrożnieni\w*|pogotowi\w*|wywóz\w*|odbi\w+\s+(?:i\s+transport\w*\s+)?(?:ścieków|nieczystości|osad)|"
    r"monitoring\w*|inspekcj\w+\s+tv|telewizyjn\w*\s+inspekc\w*|przegląd\w*|serwis\w*|umow\w+\s+ramow\w*|sukcesywn\w*",
    re.I,
)
_DELIVERY = re.compile(r"^\W*(?:dostaw\w+|zakup\w*|najem|dzierżaw\w*|leasing\w*)\b", re.I)
_BUILD = re.compile(r"\b(?:budow\w*|rozbudow\w*|wybudowani\w*|wykonani\w+\s+(?:sieci|kanaliz|wodoc|przyłącz)\w*|dobudow\w*|"
                    r"uzbrojeni\w*|zaprojektowani\w*\s+i\s+wybud\w*)", re.I)
_RENOV = re.compile(r"\b(?:przebudow\w*|modernizac\w*|remont\w*|renowac\w*|wymian\w*|rekonstrukc\w*|relining\w*|bezwykopow\w*|"
                    r"odtworzeni\w*|naprawa\w*|napraw\w*|rehabilitac\w*|adaptac\w*|unowocześni\w*|doposażeni\w*|intensyfikac\w*)", re.I)


@dataclass
class WodkanTag:
    relevance: str                       # core | component | cpv_only | none
    primary: str | None                  # WOD/SAN/OCZ/SUW/DESZ/INNE
    subsectors: list[str] = field(default_factory=list)
    scope_kind: str = "works"            # works | design_only | supervision | maintenance | delivery
    work_type: str | None = None         # build | renovation | mixed | None
    design_build: bool = False
    why: str = ""                        # explanation for the expert panel

    @property
    def primary_name(self) -> str | None:
        return SUBSECTOR_NAMES.get(self.primary) if self.primary else None


def _find_sub(text: str) -> list[tuple[int, str, str]]:
    hits = []
    for k, rx in _SUB_RX:
        for m in rx.finditer(text):
            hits.append((m.start(), k, m.group(0)))
    # remove SAN hits that are inside a DESZ "kanalizacji deszczowej" span
    desz_spans = [(m.start(), m.end()) for m in _SUB_RX[2][1].finditer(text)]
    out = []
    for pos, k, w in hits:
        if k == "SAN" and any(a <= pos < b for a, b in desz_spans):
            continue
        if k == "SAN" and re.search(r"deszcz|burz|opadow", text[pos + len(w): pos + len(w) + 30], re.I):
            k = "DESZ"   # e.g. "kolektora kanalizacji deszczowej", "kanału ... deszczowego"
        if k == "WOD" and re.match(r"wodno[\s-]*kanaliz|wod[\s.-]*kan", w, re.I):
            out.append((pos, "WOD", w))
            out.append((pos + 1, "SAN", w))
            continue
        out.append((pos, k, w))
    out.sort()
    return out


def classify(title: str | None, description: str | None = None, cpv_main: str | None = None,
             cpv_all: str | None = None, order_type: str | None = None) -> WodkanTag:
    title = title.strip() if isinstance(title, str) else ""
    desc = description[:1500] if isinstance(description, str) else ""
    cpv_main = cpv_main[:8] if isinstance(cpv_main, str) else ""
    order_type = order_type if isinstance(order_type, str) else None
    hits = _find_sub(title)
    other = _OTHER.search(title)
    source = "title"
    if not hits:
        dh = _find_sub(desc[:600])
        if dh:
            hits, source = dh, "description"
            other = _OTHER.search(desc[:600]) if not other else other
    subs: list[str] = []
    for _, k, _w in hits:
        if k not in subs:
            subs.append(k)
    # relevance
    if hits:
        first_w = hits[0][0]
        if other and other.start() < first_w and source == "title":
            relevance = "component"
            why = f"other object first: '{other.group(0)}' before '{hits[0][2]}'"
        elif other and source == "description" and other.start() < first_w:
            relevance = "component"
            why = f"vague title; description mentions '{other.group(0)}' before '{hits[0][2]}'"
        else:
            relevance = "core"
            why = f"{source} keyword '{hits[0][2]}'"
        primary = hits[0][1]
    elif cpv_main in _STRONG_CPV and not other:
        relevance, primary = "cpv_only", _CPV_SUB.get(cpv_main) or "INNE"
        subs = [primary]
        why = f"no keyword; main CPV {cpv_main}"
    else:
        relevance, primary = "none", None
        why = f"no wod-kan keyword{'; other: ' + other.group(0) if other else ''}"
    if relevance in ("core", "cpv_only") and primary is None:
        primary = "INNE"
    # scope kind
    scope = "works"
    if order_type and order_type not in ("Works",):
        scope = "delivery" if order_type == "Delivery" else "services"
    if _DELIVERY.search(title):
        scope = "delivery"
    elif _SUPERVISION.search(title):
        scope = "supervision"
    elif _DESIGN_ONLY.search(title) and not _DESIGN_BUILD.search(title):
        scope = "design_only"
    elif _MAINTENANCE.search(title):
        scope = "maintenance"
    # work type
    b, r = _BUILD.search(title), _RENOV.search(title)
    work_type = "mixed" if (b and r) else "build" if b else "renovation" if r else None
    db = bool(_DESIGN_BUILD.search(title) or _DESIGN_BUILD.search(desc))
    return WodkanTag(relevance, primary, subs, scope, work_type, db, why)


if __name__ == "__main__":
    tests = [
        "Budowa sieci kanalizacji sanitarnej w miejscowości X",
        "Przebudowa drogi gminnej wraz z budową kanalizacji deszczowej",
        "Budowa kanalizacji sanitarnej z wymianą odcinka wodociągu",
        "Rozbudowa i przebudowa oczyszczalni ścieków w Y",
        "Modernizacja stacji uzdatniania wody w Kwilczu",
        "Budowa sieci wodno-kanalizacyjnej w Gminie Kłodzko",
        "Remont izolacji przeciwwilgociowej piwnic, remont instalacji odprowadzającej wodę opadową",
        "Zaprojektowanie i wybudowanie kanalizacji sanitarnej w formule zaprojektuj i wybuduj",
        "Opracowanie dokumentacji projektowej budowy sieci wodociągowej",
        "Usuwanie awarii sieci wodociągowej w 2023 r.",
        "Budowa zbiornika retencyjnego wód opadowych",
        "Budowa sali gimnastycznej wraz z przyłączem wodociągowym",
        "Zadanie 3 w miejscowości Z",
    ]
    for t in tests:
        print(classify(t, cpv_main="45231300"), "<=", t)
