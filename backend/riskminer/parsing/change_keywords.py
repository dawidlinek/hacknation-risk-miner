"""
change_keywords.py - cheap keyword pre-classifier for contract-change reasons ("Przyczyny dokonania
zmian", fields 5.3 in AgreementUpdateNotice and 5.4.4 in ContractPerformingNotice).

Multi-label: returns every category whose pattern matches (reason + short description).
Use it to (a) pre-sort texts for expert review, (b) route only ambiguous texts to an LLM,
(c) give rough corpus-wide frequencies. Calibrated against the hand-labelled gold sample
(gold_change_reasons.csv); see docs/research/05_bzp_corpus_stats.md for precision notes.
Category codes follow the expert catalogue R01-R15 plus proposed new N-* categories.
"""
from __future__ import annotations

import re

CATEGORY_NAMES = {
    "R01": "Niepełny lub niespójny zakres (braki/błędy dokumentacji, przedmiaru)",
    "R02": "Niedostateczne rozpoznanie stanu istniejącego (grunt, woda gruntowa, stan techniczny, nieznane obiekty)",
    "R03": "Kolizje, dostęp do terenu i prawa do nieruchomości",
    "R04": "Decyzje, pozwolenia, uzgodnienia, gestorzy sieci (podmioty trzecie)",
    "R05": "Niejasny podział odpowiedzialności",
    "R06": "Harmonogram / zależności od innych robót i wykonawców",
    "R07": "Roboty dodatkowe/zamienne (bez wskazanej przyczyny źródłowej)",
    "R08": "Model wynagrodzenia / rozliczenie wg obmiaru / harmonogram płatności",
    "R09": "Niejednoznaczne wymagania techniczne / zmiana rozwiązania technicznego",
    "R10": "Próby, rozruch i odbiór",
    "R11": "Postępowanie (odwołania, zawarcie umowy po terminie)",
    "R12": "Wykonawca i łańcuch dostaw (materiały, urządzenia, podwykonawcy)",
    "R13": "Finansowanie, budżet, płatności, dofinansowanie",
    "R14": "Koszty eksploatacji",
    "R15": "Nieosiągnięcie efektu",
    "N-PRICE": "Waloryzacja / wzrost cen / inflacja / wojna w Ukrainie",
    "N-COVID": "COVID-19",
    "N-WEATHER": "Warunki atmosferyczne",
    "N-CLIENT": "Zmiana/rozszerzenie zakresu na życzenie zamawiającego",
    "N-SCOPE-RED": "Ograniczenie zakresu / roboty zaniechane",
    "N-LAW": "Zmiana przepisów (VAT, płaca minimalna, ustawy)",
    "N-FORMAL": "Zmiany formalne / redakcyjne / personalne (bez wpływu na ryzyko)",
}

PATTERNS = {
    "N-PRICE": r"waloryz|wzrost\w*\s+(?:cen|koszt)|cen\w*\s+(?:materiał|paliw|energii|stali|rynkow)|inflac|wojn\w*|agresj\w*|ukrain|"
               r"art\.?\s*439|wskaźnik\w*\s+(?:cen|gus)|nadzwyczajn\w+\s+wzrost",
    "N-COVID": r"covid|epidemi|pandemi|sars",
    "N-WEATHER": r"atmosferyczn|pogod|intensywn\w*\s+opad|opad\w*\s+(?:deszczu|śniegu|atmosf)|obfit\w*\s+opad|nawalni|ulew|mroz|"
                 r"ujemn\w+\s+temperatur|nisk\w*\s+temperatur|śnieg|okres\w*\s+zimow|warunk\w*\s+zimow|powodzi|powódź|"
                 r"podtopie|roztop|wezbra|susz[ay]\b",
    "R02": r"wod\w*\s+gruntow|warunk\w*\s+gruntow|grunt\w*\s+(?:nienośn|słab|organiczn|nasypow)|kurzawk|nawodni|igłofiltr|"
           r"odwodnieni\w*\s+wykop|stan\w*\s+techniczn|niezinwentaryzowan|nieinwentaryzowan|nienaniesion|nieujawnion|ujawnion|"
           r"nieznan\w+|okazał\w*\s+się|stwierdzono\s+(?:w\s+trakcie|podczas|po)|w\s+trakcie\s+(?:realizacji|robót|wykonywania)\w*\s+"
           r"(?:okazało|stwierdzono|ujawniono|natrafiono)|natrafion|archeolog|niewybuch|skał\w*|głaz|przeszk\w*\s+podziemn|"
           r"azbest|zły\s+stan|złego\s+stanu|zdegradowan|skorodowan|zużyt",
    "R03": r"kolizj|właściciel\w*|wejści\w*\s+w\s+teren|dostęp\w*\s+do\s+(?:terenu|nieruchom|działk)|nieruchomoś|służebnoś|"
           r"przekazani\w*\s+(?:terenu|placu)|brak\w*\s+(?:zgody|możliwości\s+wejścia)|sprzeciw\w*|protest\w*\s+mieszka|odmow\w*\s+"
           r"(?:zgody|udostępn)|zmian\w*\s+(?:trasy|przebiegu)|przebieg\w*\s+(?:sieci|trasy)",
    "R04": r"decyzj\w*\s+(?:o|środowisk|administr|wodnopr|lokaliz|zezwal)|pozwoleni|zgłoszeni\w*\s+(?:rob|budow|wodno)|uzgodni|opini\w*\s+(?:konserw|rdoś|sanep|wód|zarządc|gestor)|konserwator|wod\w*\s+polsk|zarządc\w*|gestor|"
           r"operator\w*\s+(?:sieci|systemu)|przyłącz\w*\s+(?:energet|elektroenerget)|zasilani\w*\s+energ|pge\b|tauron|enea|energa|"
           r"warunk\w*\s+(?:techniczn|przyłączeni)|zajęci\w*\s+pasa|organizac\w*\s+ruchu|starost|nadzor\w*\s+budowlan|pinb|"
           r"wodnoprawn|rdoś|środowiskow|zezwoleni|sanepid|pkp|gddkia|zarząd\w*\s+dróg",
    "R06": r"harmonogram(?!\w*\s+rzeczowo)\w*\s+(?:robót|prac|realizacji)|koordynac|równoległ|inn\w+\s+(?:wykonawc|inwestycj|zadani|umow|robót)|kolejnoś|"
           r"zależn\w*\s+od|wstrzymani\w*\s+(?:robót|prac)|przestoj|skumulowan|uzależnion\w*\s+od\s+(?:zakończenia|wykonania|realizacji)",
    "R07": r"robot\w*\s+(?:dodatkow|zamienn|uzupełniaj|nieprzewidzian|konieczn)|prac\w*\s+(?:dodatkow|zamienn)|zwiększeni\w*\s+zakresu|"
           r"protok\w*\s+konieczn|roboty\s+niezbędne|455\s*ust\.?\s*1\s*pkt\.?\s*3",
    "R01": r"błęd\w*\s+(?:w\s+)?(?:dokument|projekt|przedmiar|kosztorys)|niezgodnoś\w*|nie\s+(?:zostały|został|zostało|była|było|były)\s+"
           r"(?:uwzględnion|przewidzian|ujęt|zaprojektowan)\w*|nieujęt|nieprzewidzian\w*\s+w\s+(?:dokumentacji|projekcie|przedmiar)|"
           r"pominięt|brak\w*\s+w\s+(?:dokumentacji|projekcie|przedmiar)|przedmiar\w*|niekompletn|nieścisłoś|rozbieżnoś",
    "R09": r"przeprojekt|zmian\w*\s+(?:projekt|rozwiązań|rozwiązania|technologii|materiał|parametr)|rozwiązani\w*\s+(?:zamienn|alternatyw)|"
           r"zamian\w*\s+(?:materiał|urządze|rur)|projekt\w*\s+zamienn|zmian\w*\s+średnic|lepsz\w*\s+parametr|zmian\w*\s+technolog",
    "N-CLIENT": r"na\s+(?:wniosek|prośbę|życzenie)\s+zamawiającego|z\s+inicjatywy\s+zamawiającego|zamawiający\s+(?:zlecił|postanowił|"
                r"zdecydował|podjął)|dodatkow\w+\s+(?:przyłącz|odcin|ulic|odbiorc)|nowych\s+(?:odbiorców|mieszkańców|budynków|przyłącz)|"
                r"wnios\w*\s+mieszkańc|rozszerzeni\w*\s+zakresu|potrzeb\w*\s+(?:zamawiającego|mieszkańców)",
    "N-SCOPE-RED": r"zmniejszeni\w*\s+(?:zakresu|wynagrodz|wartości)|ograniczeni\w*\s+zakresu|rezygnac|wyłączeni\w*\s+z\s+zakresu|"
                   r"nie\s+będ\w*\s+wykonywan|robót\s+zaniechanych|odstąpi",
    "R08": r"obmiar|kosztorys\w*\s+powykonawcz|rozliczeni\w*\s+(?:końcow|powykonawcz|robót|faktur|wynagrodz|częściow)|sposob\w*\s+rozlicz|faktycznie\s+wykonan|ilości\s+(?:robót|rzeczywist)|ryczałt|kosztorysow|"
           r"harmonogram\w*\s+rzeczowo|płatnoś\w*\s+częściow|fakturowan|zaliczk|termin\w*\s+płatnoś|częściow\w+\s+odbior",
    "R10": r"rozruch|odbior\w*\s+(?:końcow|techniczn)|odbiór|próby|prób\w*\s+(?:szczeln|ciśnien)|badani\w*\s+(?:bakteriolog|wody|szczel)|"
           r"inspekcj\w*\s+(?:tv|kamer)|dokumentacj\w*\s+powykonawcz|pomiar\w*\s+geodezyjn|inwentaryzacj\w*\s+powykonawcz|"
           r"pozwoleni\w*\s+na\s+użytkowanie|kontrol\w*\s+(?:jakości|szczeln)",
    "R11": r"związani\w*\s+ofertą|odwołani\w*|\bkio\b|przedłużając\w+\s+się\s+(?:procedur|postępow)|zawarci\w*\s+umowy\s+po|"
           r"termin\w*\s+związania",
    "R12": r"dostaw\w*\s+(?:materiał|urządzeń|pomp|element|rur)|dostępnoś\w*\s+(?:materiał|urządzeń)|brak\w*\s+(?:materiał|dostęp)|"
           r"termin\w*\s+dostaw|producent|niedostępn|czas\w*\s+(?:oczekiwania|dostawy)|podwykonawc|upadłoś|likwidac|zmian\w*\s+wykonawcy|"
           r"cesj|konsorcj|przekształc|następc\w*\s+prawn|455\s*ust\.?\s*1\s*pkt\.?\s*2|niedobór|brak\w*\s+pracownik",
    "R13": r"dofinansowan|finansowani|środk\w*\s+(?:finansow|budżet|zewnętrzn|z\s)|budżet|polski\w*\s+ład|rządow\w+\s+(?:fundusz|program)|"
           r"rfil|\bkpo\b|wniosk\w*\s+o\s+płatność|refundac|brak\w*\s+środków|programu?\s+inwestycji\s+strategicznych|wpłat|"
           r"\bwpf\b|uchwał\w*\s+budżet",
    "N-LAW": r"zmian\w*\s+(?:przepisów|ustawy|prawa|stawki|stawek)|nowelizac|minimaln\w+\s+(?:wynagrodz|stawk)|podatk\w*\s+(?:vat|od\s+towarów)|"
             r"stawk\w*\s+(?:vat|podatku)|ppk\b|składek",
    "N-FORMAL": r"oczywist\w*\s+omyłk|omyłk\w*|redakcyjn|numer\w*\s+rachunku|zmian\w*\s+(?:nazwy|adresu|siedziby|rachunku|osoby|"
                r"kierownika|inspektora|osób)|zabezpieczeni\w*\s+należyt|gwarancj\w*\s+(?:ubezpiecz|bankow)|doprecyzowa|"
                r"uporządkowani|aktualizac\w*\s+(?:zapis|danych)|błęd\w*\s+(?:pisarsk|rachunk)",
}
_RX = {k: re.compile(v, re.I) for k, v in PATTERNS.items()}


def keyword_categories(reason: str | None, description: str | None = None) -> list[str]:
    text = " ".join(t for t in (reason, description) if isinstance(t, str))
    return [k for k, rx in _RX.items() if rx.search(text)]


# simple signals about WHAT was changed (independent of WHY)
WHAT = {
    "time": re.compile(r"termin\w*|przedłuż\w*|wydłuż\w*|do\s+dnia\s+\d|\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2}", re.I),
    "price": re.compile(r"wynagrodz\w*|wartoś\w*|kwot\w*|cen\w*\b|zł\b|pln\b|brutto|netto", re.I),
    "scope": re.compile(r"zakres\w*|robot\w*\s+(?:dodatkow|zamienn)|zaniechan|rezygnac", re.I),
}


def what_changed(reason: str | None, description: str | None = None) -> list[str]:
    text = " ".join(t for t in (reason, description) if isinstance(t, str))
    return [k for k, rx in WHAT.items() if rx.search(text)]
