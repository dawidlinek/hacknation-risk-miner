"""Target-field registry and known formats for the import agent. A mapping may only point at a field listed here;
anything else stays a proposal and is never imported."""
from __future__ import annotations

import re

from riskminer.ingest import ids

# field -> (Polish label, rule)
TARGET_FIELDS: dict[str, tuple[str, str]] = {
    "project.rm_id": ("identyfikator rekordu", "required_text"),
    "project.title": ("nazwa przedsięwzięcia", "required_text"),
    "organization.nip": ("NIP odbiorcy", "nip_checksum"),
    "organization.id_type": ("rodzaj identyfikatora odbiorcy", "text_no_analysis"),
    "organization.name": ("nazwa odbiorcy", "required_text"),
    "organization.org_type": ("typ odbiorcy", "text_no_analysis"),
    "project.country": ("kraj", "text_no_analysis"),
    "project.teryt_woj": ("kod województwa (TERYT)", "teryt_woj"),
    "project.woj_name": ("województwo", "text_no_analysis"),
    "project.city": ("siedziba odbiorcy", "text_no_analysis"),
    "project.scope_text": ("zakres rekordu", "text_no_analysis"),
    "project.public_id_type": ("rodzaj identyfikatora publicznego", "text_no_analysis"),
    "project.public_id": ("identyfikator publiczny (BZP / KPO / TED)", "public_id_format"),
    "project.thematic_area": ("obszar tematyczny", "text_no_analysis"),
    "project.order_type": ("rodzaj zamówienia", "text_no_analysis"),
    "project.legal_regime": ("reżim prawny", "text_no_analysis"),
    "project.currency": ("waluta rozliczeń", "text_no_analysis"),
    "project.status": ("status przedsięwzięcia", "text_no_analysis"),
    "project.record_source": ("źródło rekordu", "text_no_analysis"),
    "project.record_date": ("data sporządzenia rekordu", "date_format"),
    "project.record_version": ("wersja rekordu", "text_no_analysis"),
    "project.annotation": ("adnotacja instytucji", "text_no_analysis"),
    "project.value": ("wartość przedsięwzięcia", "money_requires_vat_basis"),
    "project.subsidy": ("dofinansowanie", "money_requires_vat_basis"),
    "project.description": ("opis", "text_no_analysis"),
    "project.note": ("uwagi", "text_no_analysis"),
    "procedure.bzp_number": ("numer ogłoszenia BZP", "bzp_format"),
    "project.kpo_number": ("numer projektu KPO", "kpo_format"),
}

# header synonym -> field (folded, punctuation-free)
SYNONYMS: dict[str, str] = {
    "identyfikator rekordu": "project.rm_id", "id rekordu": "project.rm_id", "id": "project.rm_id",
    "nazwa przedsiewziecia": "project.title", "nazwa projektu": "project.title", "tytul projektu": "project.title",
    "przedmiot zamowienia": "project.title", "nazwa zadania": "project.title",
    "identyfikator odbiorcy": "organization.nip", "nip odbiorcy": "organization.nip", "nip": "organization.nip",
    "nip beneficjenta": "organization.nip", "nip zamawiajacego": "organization.nip",
    "rodzaj identyfikatora odbiorcy": "organization.id_type",
    "nazwa odbiorcy": "organization.name", "beneficjent": "organization.name", "nazwa beneficjenta": "organization.name",
    "zamawiajacy": "organization.name", "nazwa zamawiajacego": "organization.name",
    "typ odbiorcy": "organization.org_type", "kraj": "project.country",
    "kod wojewodztwa teryt": "project.teryt_woj", "kod wojewodztwa": "project.teryt_woj", "teryt": "project.teryt_woj",
    "wojewodztwo": "project.woj_name", "siedziba odbiorcy": "project.city", "miejscowosc": "project.city",
    "zakres rekordu": "project.scope_text", "rodzaj identyfikatora publicznego": "project.public_id_type",
    "identyfikator publiczny": "project.public_id", "nr ogloszenia": "procedure.bzp_number",
    "numer ogloszenia": "procedure.bzp_number", "numer ogloszenia bzp": "procedure.bzp_number",
    "numer projektu kpo": "project.kpo_number", "nr projektu kpo": "project.kpo_number",
    "obszar tematyczny": "project.thematic_area", "rodzaj zamowienia": "project.order_type",
    "rezim prawny": "project.legal_regime", "waluta rozliczen": "project.currency", "waluta": "project.currency",
    "status przedsiewziecia": "project.status", "status": "project.status", "zrodlo rekordu": "project.record_source",
    "data sporzadzenia rekordu": "project.record_date", "wersja rekordu": "project.record_version",
    "adnotacja instytucji": "project.annotation", "adnotacja": "project.annotation",
    "kwota": "project.value", "wartosc": "project.value", "wartosc przedsiewziecia": "project.value",
    "wartosc projektu": "project.value", "wartosc calkowita": "project.value", "koszt calkowity": "project.value",
    "dofinansowanie": "project.subsidy", "kwota dofinansowania": "project.subsidy",
    "opis": "project.description", "uwagi": "project.note",
}

# the organizer dataset (materials/starter/Risk_Miner_dane_projekty.xlsx, sheet Projekty, 23 columns)
KNOWN_FORMATS: dict[str, dict] = {
    "zestaw organizatora": {
        "format": "xlsx", "sheet": "Projekty",
        "headers": ["Lp.", "Identyfikator rekordu", "Rodzaj identyfikatora odbiorcy", "Identyfikator odbiorcy", "Nazwa odbiorcy",
                    "Typ odbiorcy", "Kraj", "Kod województwa (TERYT)", "Województwo", "Siedziba odbiorcy",
                    "Nazwa przedsięwzięcia", "Zakres rekordu", "Rodzaj identyfikatora publicznego", "Identyfikator publiczny",
                    "Obszar tematyczny", "Rodzaj zamówienia", "Reżim prawny", "Waluta rozliczeń", "Status przedsięwzięcia",
                    "Źródło rekordu", "Data sporządzenia rekordu", "Wersja rekordu", "Adnotacja instytucji"]},
}


def norm(h: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", ids.fold(h or "")).strip()


def field_for(header: str) -> str | None:
    n = norm(header)
    if n in SYNONYMS:
        return SYNONYMS[n]
    # 'NIP odbiorcy (10 cyfr)' -> drop a trailing parenthesis / unit
    n2 = re.sub(r"\s+(?:zl|pln|brutto|netto)$", "", re.sub(r"\s*\(.*\)$", "", n))
    return SYNONYMS.get(n2)


def match_fraction(headers: list[str], known: list[str]) -> float:
    a, b = {norm(h) for h in headers if h}, {norm(h) for h in known if h}
    return len(a & b) / max(1, len(a | b))
