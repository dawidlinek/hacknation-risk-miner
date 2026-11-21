#!/usr/bin/env bash
# Working request examples verified 2026-11-21 for Risk Miner "other sources" research.
# Usage: bash examples.sh <section>   (sections: ted ted_modif ted_ft wl bir bip cru bk kio nik bdl mapa kposk)
set -euo pipefail
UA='Mozilla/5.0 (RiskMiner research)'
NIP=${NIP:-8590012007}   # Gmina Nowogard (dataset RM-2026-020/021)

case "${1:-}" in
ted)  # TED API v3: notices of a buyer by NIP (no key). Try also "NIP $NIP", REGON, hyphenated variants.
  curl -s -X POST https://api.ted.europa.eu/v3/notices/search -H 'Content-Type: application/json' -d "{
    \"query\":\"organisation-identifier-buyer=$NIP OR buyer-identifier=$NIP\",
    \"fields\":[\"publication-number\",\"notice-type\",\"publication-date\",\"notice-title\",\"classification-cpv\",\"procedure-identifier\",\"internal-identifier-proc\",\"document-url-lot\"],
    \"limit\":50}" ;;
ted_modif)  # PL wod-kan contract modification notices (eForms) with reasons
  curl -s -X POST https://api.ted.europa.eu/v3/notices/search -H 'Content-Type: application/json' -d '{
    "query":"notice-type=can-modif AND buyer-country=POL AND classification-cpv IN (45231300 45232400 45252100 45232410 45232411 45232423 45252127) AND publication-date>=20250101",
    "fields":["publication-number","buyer-name","organisation-identifier-buyer","modification-justification","modification-description","modification-reason-description","result-value-notice","modification-previous-notice-identifier","internal-identifier-proc"],
    "limit":50, "paginationMode":"ITERATION"}' ;;
ted_ft)  # full-text search for KPO numbers
  curl -s -X POST https://api.ted.europa.eu/v3/notices/search -H 'Content-Type: application/json' -d '{"query":"FT~\"KPOD.03.15\"","fields":["publication-number","buyer-name"],"limit":50}' ;;
wl)   # Biała lista VAT: NIP -> name, REGON, KRS, address (max 30 NIPs/request, 100 search requests/day)
  curl -s "https://wl-api.mf.gov.pl/api/search/nips/$NIP,6941566139?date=$(date +%F)" ;;
bir)  # GUS BIR1.1 TEST environment with public test key (anonymised street; real NIP/REGON/TERYT/website)
  U=https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc
  SID=$(curl -s -H 'Content-Type: application/soap+xml; charset=utf-8' -d '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07"><soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing"><wsa:To>'$U'</wsa:To><wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action></soap:Header><soap:Body><ns:Zaloguj><ns:pKluczUzytkownika>abcde12345abcde12345</ns:pKluczUzytkownika></ns:Zaloguj></soap:Body></soap:Envelope>' $U | grep -o '<ZalogujResult>[^<]*' | sed 's/<ZalogujResult>//')
  curl -s -H 'Content-Type: application/soap+xml; charset=utf-8' -H "sid: $SID" -d '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07" xmlns:dat="http://CIS/BIR/PUBL/2014/07/DataContract"><soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing"><wsa:To>'$U'</wsa:To><wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action></soap:Header><soap:Body><ns:DaneSzukajPodmioty><ns:pParametryWyszukiwania><dat:Nip>'$NIP'</dat:Nip></ns:pParametryWyszukiwania></ns:DaneSzukajPodmioty></soap:Body></soap:Envelope>' $U ;;
bip)  # Central BIP register (undocumented JSON used by gov.pl/web/bip); TERYT dictionaries too
  B=https://aplikacje.gov.pl/app/bip-back
  curl -s -A "$UA" -G "$B/api/subjects" --data-urlencode archive=false --data-urlencode hasContactCard=true --data-urlencode name=Kleszczew
  curl -s -A "$UA" "$B/api/dictionaries/voivodeships/32/districts/3204/communes" ;;
cru)  # Centralny Rejestr Umów JSFP public search (contracts from 2026-07-01, incl. annexes)
  curl -s -A "$UA" -H 'Content-Type: application/json' -X POST 'https://rejestrumow.gov.pl/api-dp/v1/agreements/search?offset=0&limit=20' \
    -d "{\"menuGlowne\":{\"nip\":\"$NIP\",\"przedmiotUmowy\":\"kanaliz\"}}"
  # detail: curl -s https://rejestrumow.gov.pl/api-dp/v1/agreement/<idUmowy>
  # annexes only: -d '{"menuGlowne":{"przedmiotUmowy":"kanalizacji"},"zmianyUmowy":{"rodzajZmiany":"TSU02"}}'
  ;;
bk)   # Baza Konkurencyjności 2021 (undocumented JSON behind the SPA)
  B=https://bazakonkurencyjnosci.funduszeeuropejskie.gov.pl
  curl -s -A "$UA" -H 'Content-type: application/json; charset=utf-8' \
    "$B/api/announcements/search?page=1&limit=20&sort=default&advertiserIdentificationNumber=6941566139&status%5B0%5D=PUBLISHED&status%5B1%5D=RESOLVED&status%5B2%5D=CANCELLED&status%5B3%5D=CLOSED"
  # detail: $B/api/announcements/270126   award: $B/api/announcements/270126/settlement
  # by project number: &full_number=FEDS.02.01-IZ.00-0015/25
  ;;
kio)  # KIO rulings: POST form -> HTML fragment; details /Home/Details/<id>; text /Home/PdfContent/<id>?Kind=KIO
  curl -s -A "$UA" -X POST https://orzeczenia.uzp.gov.pl/Home/GetResults -H 'X-Requested-With: XMLHttpRequest' \
    --data-urlencode 'Phrase="Gmina Nowogard"' --data-urlencode Fle=1 --data-urlencode SCnt=1 \
    --data-urlencode Kind=KIO --data-urlencode Pg=1 --data-urlencode CountStats=True ;;
nik)  # NIK audit search (JSON with embedded XML list)
  curl -s -A "$UA" -H 'X-Requested-With: XMLHttpRequest' -X POST 'https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/fmax,,strona,1.html' \
    --data-urlencode 'temat=ściek' --data-urlencode numer= --data-urlencode dzialy=0 --data-urlencode jednostka= \
    --data-urlencode jednjednostka= --data-urlencode dataodx=2010-01-01 --data-urlencode datadox=$(date +%F) \
    --data-urlencode rodzaj= --data-urlencode zakres=dowolny ;;
bdl)  # GUS BDL: length of active sewer network (var 494) for gmina Zagrodno (unit 030210126052)
  curl -s -H 'Accept: application/json' "https://bdl.stat.gov.pl/api/v1/data/by-unit/030210126052?var-id=494&var-id=9153&format=json" ;;
mapa) # Mapa Dotacji: KPO B3.1.1 list (631 projects, 10/page, page_no=1..64); HTML scraping
  curl -s -A "$UA" -G https://mapadotacji.gov.pl/projekty/ --data-urlencode search-program=29425 \
    --data-urlencode search-number-name-activity=30818 --data-urlencode page_no=1 ;;
kposk) # KPOŚK annual report xlsx (CC BY 4.0) from dane.gov.pl (~3 MB)
  curl -s -L -o kposk_2024.xlsx "https://api.dane.gov.pl/resources/1491599,sprawozdanie-kposk-za-2024-rok/file" ;;
*) echo "sections: ted ted_modif ted_ft wl bir bip cru bk kio nik bdl mapa kposk" ;;
esac
