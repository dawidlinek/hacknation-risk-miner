"""Change-cause label set: catalogue R01–R18 plus the gold set's N-* codes (docs/impl/llm.md §2.3).

Read from `catalogue/wod-kan/cause_labels.yaml` (sector pack, session D) when present, else these defaults (drafted by
L from the gold-set guide and the live probe). Format of the YAML: `labels: [{code, name, definition, maps_to?}]`."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from riskminer.config import settings

DEFAULT: dict[str, str] = {
    "R01": "Niepełny lub niespójny zakres: braki lub błędy dokumentacji projektowej, przedmiaru, PFU, pominięte roboty",
    "R02": "Niedostateczne rozpoznanie stanu istniejącego: grunt, woda gruntowa, stan techniczny obiektu, nieznane obiekty "
           "i sieci w ziemi, odkrycia archeologiczne, niewybuchy, azbest",
    "R03": "Kolizje z uzbrojeniem terenu, dostęp do terenu, prawa do nieruchomości, zgody właścicieli",
    "R04": "Decyzje, pozwolenia, uzgodnienia, warunki gestorów sieci, zarządców dróg i innych podmiotów trzecich",
    "R05": "Niejasny podział odpowiedzialności między stronami lub uczestnikami procesu",
    "R06": "Nierealistyczny harmonogram, zależność od innych robót lub wykonawców na tym samym terenie",
    "R07": "Roboty dodatkowe lub zamienne, gdy tekst nie podaje ich przyczyny źródłowej",
    "R08": "Model wynagrodzenia: rozliczenie według obmiaru, zmiana ilości w kosztorysie, harmonogram płatności",
    "R09": "Niejednoznaczne wymagania techniczne, zmiana rozwiązania technicznego, technologii lub materiału",
    "R10": "Próby, rozruch, odbiory, pomiary i dokumentacja powykonawcza",
    "R11": "Postępowanie przetargowe: odwołania, unieważnienia, zawarcie umowy po terminie",
    "R12": "Zdolność wykonawcy i łańcuch dostaw: brak materiałów i urządzeń, opóźnione dostawy, podwykonawcy, upadłość",
    "R13": "Finansowanie, budżet zamawiającego, płatności, dofinansowanie, termin programu",
    "R14": "Koszty eksploatacji i utrzymania po oddaniu obiektu",
    "R15": "Nieosiągnięcie efektu: przepustowość, jakość wody lub ścieków, liczba przyłączonych mieszkańców",
    "R16": "Warunki atmosferyczne i sezonowość: opady, mróz, susza, okres zimowy",
    "R17": "Koordynacja z inwestycjami innych podmiotów (drogi, gazociągi, inne sieci budowane w tym samym czasie)",
    "R18": "Zależność od zadań powiązanych (inna część projektu, oczyszczalnia, przepompownia budowana osobno)",
    "N-PRICE": "Waloryzacja, wzrost cen materiałów i robocizny, inflacja, skutki wojny w Ukrainie dla cen",
    "N-COVID": "Pandemia COVID-19 i jej skutki",
    "N-CLIENT": "Zmiana lub rozszerzenie zakresu na życzenie zamawiającego (nowe potrzeby, dodatkowe odcinki)",
    "N-SCOPE-RED": "Ograniczenie zakresu, roboty zaniechane, rezygnacja z części zamówienia",
    "N-LAW": "Zmiana przepisów prawa (stawka VAT, płaca minimalna, ustawy)",
    "N-FORMAL": "Zmiany formalne, redakcyjne, personalne lub rachunkowe bez wpływu na ryzyko",
    "N-UNSPEC": "Brak faktycznej przyczyny: tylko formuła ustawowa (art. 455) albo powtórzenie skutku bez powodu",
}
# N-WEATHER from the gold set maps to R16 (weather) since R16 exists in the catalogue as a proposal
ALIASES = {"N-WEATHER": "R16"}


@lru_cache
def labels() -> dict[str, str]:
    p = Path(settings().catalogue_dir) / "wod-kan" / "cause_labels.yaml"
    if p.exists():
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            out = {x["code"]: x.get("definition") or x.get("name") for x in d.get("labels") or [] if x.get("code")}
            if len(out) >= 10:
                return out
        except Exception:  # noqa: BLE001
            pass
    return dict(DEFAULT)


def codes() -> list[str]:
    return list(labels())


def normalise_code(c: str | None) -> str | None:
    if not c:
        return None
    c = c.strip().upper()
    c = ALIASES.get(c, c)
    return c if c in labels() else None
