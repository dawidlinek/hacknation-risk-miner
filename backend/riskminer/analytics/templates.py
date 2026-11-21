"""Every Polish sentence the engine produces (summary, Q cards, flags, limitations). Never LLM-written.

House style: no em dashes, no middle dots; frequencies ("w 52 z 82 umów"); at most two significant digits on
forecasts; decimal comma.
"""
from __future__ import annotations

import math


def pl_num(x: float | None, decimals: int = 0) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "b.d."
    s = f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",")


def pct(x: float | None, decimals: int = 0) -> str:
    return "b.d." if x is None else f"{pl_num(x * 100, decimals)}%"


def months(x: float | None) -> str:
    return "b.d." if x is None else f"{pl_num(x, 1 if x < 100 else 0)} mies."


def mln(x: float | None, decimals: int = 2) -> str:
    return "b.d." if x is None else f"{pl_num(x / 1e6, decimals)} mln zł"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def umow(n: int) -> str:
    return f"{pl_num(n)} {plural(n, 'umowa', 'umowy', 'umów')}"


def summary_sentence(n: int, klass: str, late: float | None, plan_m: float | None, p_on: float | None,
                     t80_m: float | None, ppk_mln: float | None, ppk_pct: float | None, insufficient: bool) -> str:
    if insufficient:
        return (f"Za mało podobnych umów (n = {n}), żeby podać szanse na termin. Pokazujemy pojedyncze przypadki "
                "i tło sektorowe.")
    parts = [f"Podobne inwestycje ({umow(n)}: {klass}) w {pct(late)} kończyły się po terminie."]
    if plan_m and p_on is not None and t80_m is not None:
        parts.append(f"Przy planie {pl_num(plan_m)} mies. szansa na termin to ok. {pct(p_on)}, a 8 na 10 umów "
                     f"skończyłoby się w {pl_num(t80_m, 0)} mies.")
    if ppk_mln is not None and ppk_pct is not None:
        parts.append(f"Koszt kilometra ({pl_num(ppk_mln, 2)} mln zł) jest wyższy niż w {pct(ppk_pct)} umów.")
    return " ".join(parts)


def q_time(plan_m: float) -> str:
    return f"Czy zdążysz w {pl_num(plan_m)} {plural(round(plan_m), 'miesiąc', 'miesiące', 'miesięcy')}?"


def q_budget(budget: float | None) -> str:
    return f"Czy {mln(budget, 1) if budget else 'budżet'} wystarczy?"


Q_PROGRAMME = "Czy zdążysz przed końcem programu?"

BAND_CAPTION = "8 na 10 podobnych umów"
BAND_CAPTION_PPK = "połowa podobnych umów"


def flag_f6(plan_m: float, med_m: float, p25_m: float) -> tuple[str, str]:
    return ("Termin krótszy niż typowy",
            f"{pl_num(plan_m)} mies. wobec mediany {pl_num(med_m, 1)} mies. planowanych terminów w tej grupie; "
            f"krócej planowała tylko co czwarta umowa (poniżej {pl_num(p25_m, 1)} mies.).")


def flag_f5(buffer_days: int, deadline: str, prog: str) -> tuple[str, str]:
    if buffer_days < 0:
        txt = (f"Przy typowym czasie przetargu plan kończy się {pl_num(-buffer_days)} dni po terminie programu "
               f"({prog}, {deadline}).")
    else:
        txt = (f"Między planowanym końcem a terminem programu ({prog}, {deadline}) zostaje tylko "
               f"{pl_num(buffer_days)} dni zapasu.")
    return "Termin a dofinansowanie", txt


def flag_f12(plan_m: float) -> tuple[str, str]:
    return ("Zaprojektuj i wybuduj w krótkim terminie",
            f"Projekt, decyzje i budowa mają zmieścić się w {pl_num(plan_m)} mies.; w tej formule czas uzyskania "
            "decyzji jest po stronie wykonawcy, ale zależy od organów.")


def flag_f14(plan_m: float, med_m: float) -> tuple[str, str]:
    return ("Zimowe roboty ziemne bez rezerwy",
            f"Okres robót obejmuje grudzień–luty, a termin ({pl_num(plan_m)} mies.) jest krótszy niż mediana "
            f"{pl_num(med_m, 1)} mies.")


LIMITS_BASE = [
    "Koszt liczony względem wartości umowy z ogłoszenia o wykonaniu (pole 4.4), więc dopłaty są dolną granicą.",
]
CAUSES_KW = "Przyczyny zmian rozpoznane regułami słownikowymi; część zmian nie ma rozpoznanej przyczyny."
CAUSES_AI = ("Przyczyny zmian sklasyfikował model AI (propozycje do przeglądu przez eksperta, ok. 8 na 10 trafień "
             "na próbie wzorcowej); gdzie go brak, użyto reguł słownikowych.")
CAUSES_SHORT = {"ai_then_keyword": "przyczyny: klasyfikacja AI (do przeglądu), reszta regułami",
                "keyword": "przyczyny z reguł słownikowych"}


def causes_limit(mode: str) -> str:
    return CAUSES_AI if mode == "ai_then_keyword" else CAUSES_KW
LIMIT_NOMINAL = "Koszt kilometra w cenach nominalnych (bez indeksacji GUS)."
LIMIT_LENGTH = ("Długość odczytana wyrażeniem regularnym z {source}; ma ją {cov} umów podsektora, "
                "więc koszt kilometra liczony jest na tej części.")
LENGTH_SOURCE = {"procedure.length_km": "tytułu i opisu przedmiotu zamówienia (ogłoszenie o zamówieniu, a gdy brak "
                                        "opisu, opisy części)",
                 "regex_v1": "tytułu i opisu w ogłoszeniu o wykonaniu umowy"}
LIMIT_NO_LENGTH = "Nie podano długości sieci, więc nie liczymy kosztu kilometra."
LIMIT_PLANT = "Dla oczyszczalni i stacji uzdatniania koszt kilometra nie ma sensu; miara RLM lub m³/d nie jest jeszcze liczona."
LIMIT_NO_KM_SECTOR = "Dla tego rodzaju obiektu koszt kilometra nie ma sensu, więc go nie liczymy."
LIMIT_SECTOR_EXTENSION = ("Sektor „{name}” to rozszerzenie pilotażu: podsektory, ryzyka i słownik są propozycjami do "
                          "zatwierdzenia przez eksperta, a założenia (zmiany przed przetargiem, podział ryzyk) przejęto "
                          "z wod-kan. Przypadki zweryfikowane (22 projekty) dotyczą wod-kan.")
LIMIT_NO_PROGRAMME = "Brak terminu programu finansowania, więc nie liczymy szansy na zdążenie przed jego końcem."
LIMIT_PROGRAMME_ASSUMPTION = "Termin programu „{name}” to założenie eksperta z Katalogu ({status}); termin z umowy o dofinansowanie ma pierwszeństwo."
LIMIT_NO_DOCS = "Nie dołączono dokumentów (PFU, PPU), więc sygnały z treści dokumentów nie są sprawdzone."
LIMIT_MITIGATIONS = ("Efekty zmian w symulacji to założenia eksperta z Katalogu, liczone tylko na umowach z rozpoznaną "
                     "przyczyną zmiany; danych jest mało.")
