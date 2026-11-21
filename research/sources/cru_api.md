# 📘 CRU API – Dokumentacja Integracyjna

## Informacje o wersji dokumentacji

- **Wersja API (OpenAPI):** 1.3.4
- **Wersja dokumentacji integracyjnej:** 1.3.7
- **Historia zmian:** [Przejdź do historii zmian](?doc=changelog)

### 1) Jak interpretować wersje

- **Wersja API (OpenAPI)** opisuje kontrakt techniczny endpointów: żądanie, odpowiedź, pola, typy i wymagania techniczne.
- **Wersja dokumentacji integracyjnej** opisuje zasady integracji, walidacje biznesowe, ograniczenia i przykłady użycia API.

> Uwaga: zmiana wersji dokumentacji integracyjnej nie zawsze oznacza zmianę kontraktu API OpenAPI. Aktualizacja może dotyczyć doprecyzowania opisów, przykładów lub zaleceń integracyjnych.
---

## Wprowadzenie

**CRU API** umożliwia:

- publikację oraz aktualizację umów,
- wycofanie opublikowanych umów z publikacji,
- pobieranie szczegółów umowy po identyfikatorze umowy,
- przeglądanie streszczeń umów z filtrowaniem i paginacją,
- masową weryfikację statusu istnienia umów.

API jest zabezpieczone przy użyciu klucza **X-API-KEY**.

---

## Środowiska

| Środowisko | Adres bazowy                                     |
|------------|--------------------------------------------------|
| **TEST**   | `https://jsfp-cru-test.mf.gov.pl/v1/api/publish` |
| **PROD**   | `https://jsfp.rejestrumow.gov.pl/v1/api/publish` |

Wszystkie endpointy opisane poniżej są dostępne pod powyższym adresem bazowym.

---

## Autoryzacja

Każde wywołanie API wymaga nagłówka:

```http
X-API-KEY: {twoj_klucz_api}
```

### Przykład curl

```bash
curl -X GET \
https://jsfp-cru-test.mf.gov.pl/v1/api/publish/123456789 \
-H "X-API-KEY: YOUR_API_KEY"
```

Brak lub niepoprawny klucz powoduje odpowiedź:

```http
403 Forbidden
```

Przykład:

```json
{
  "code": "FORBIDDEN",
  "message": "Brak nagłówka klucza API",
  "details": {}
}
```

---

## Uzyskanie klucza API

Klucz API jest generowany i zarządzany w aplikacji **CRU**.

### 1) Wymagania wstępne

Aby wygenerować klucz API, użytkownik musi posiadać w aplikacji CRU rolę **Publikującego**.

### 2) Kroki wygenerowania klucza

1. Zaloguj się do aplikacji **CRU**.
2. Uzyskaj lub upewnij się, że posiadasz rolę **Publikującego**.
3. Przejdź do zakładki **Moje Dane**.
4. Otwórz podzakładkę **Klucz API**.
5. Wybierz opcję **Generuj klucz**.

> Uwaga: Po wygenerowaniu klucza:
>
> - klucz zostanie wyświetlony tylko raz w celu skopiowania,
> - po zamknięciu widoku nie będzie możliwości ponownego wyświetlenia tej samej wartości klucza,
> - w przypadku utraty klucza należy wygenerować nowy.

### 3) Historia kluczy

W tej samej podzakładce **Moje Dane → Klucz API** użytkownik może sprawdzić historię kluczy.

### 4) Ważność i blokowanie klucza

- Klucz API jest ważny przez **6 miesięcy** od momentu wygenerowania.
- Po upływie tego czasu klucz zostaje zablokowany.
- Klucz zostaje również zablokowany w przypadku utraty roli Publikującego.

---

## Połączenie HTTPS i certyfikat TLS

CRU API jest dostępne wyłącznie przez **HTTPS**. Serwer używa publicznie zaufanego certyfikatu TLS, dlatego standardowe narzędzia, takie jak przeglądarka lub `curl`, nie wymagają dodatkowej konfiguracji.

### Typowe problemy integracyjne

Jeżeli wywołania wykonywane są z poziomu środowisk, które posiadają własny magazyn zaufanych certyfikatów, mogą pojawić się błędy walidacji certyfikatu, np.:

- `ORA-29024: Certificate validation failure`
- `PKIX path building failed`
- `unable to find valid certification path`

W takiej sytuacji problem dotyczy zazwyczaj konfiguracji po stronie klienta, np.:

- nieaktualny Oracle Wallet lub truststore,
- pośredni serwer proxy / SSL inspection podmieniający certyfikat,
- brak zaufania do CA używanego w organizacji.

---

## Limity wywołań i rozmiar paczek

### 1) Rate limiting dla endpointów publikacji `/v1/api/publish/**`

Wywołania endpointów publikacyjnych, w tym `POST /agreements`, są ograniczane przez bramkę API z użyciem limitera opartego o nagłówek `X-API-KEY`.

Limit dla publikacji / aktualizacji umów `POST /agreements`:

- **Limit:** `3` żądania na `1` sekundę
- **Klucz limitowania:** wartość nagłówka `X-API-KEY`
- **Timeout oczekiwania:** `0 ms`

Oznacza to, że jeśli klient wyśle kolejne żądanie z tym samym `X-API-KEY` zanim odnowi się limit, żądanie może zostać odrzucone natychmiast.

> Zalecenie integracyjne: przy przetwarzaniu wsadowym wysyłaj żądania sekwencyjnie i zachowuj odstęp co najmniej około 1 sekundy między kolejnymi wywołaniami `POST /agreements` dla tego samego klucza API.

### 2) Zachowanie przy przekroczeniu limitu

W przypadku przekroczenia limitu wywołań bramka API może zwrócić błąd ograniczenia ruchu, np. HTTP `429 Too Many Requests`.

Zalecenia po stronie klienta:

- zastosować ponawianie z opóźnieniem,
- nie wykonywać równoległych wywołań `POST /agreements` dla tego samego `X-API-KEY`,
- ograniczyć nagłe serie wywołań.

### 3) Maksymalny rozmiar paczki `POST /agreements`

Endpoint `POST /agreements` obsługuje żądania wsadowe z następującymi limitami:

- **maksymalny rozmiar paczki:** `500` elementów w jednym żądaniu,
- **zalecany rozmiar paczki:** `100–200` elementów.

Przekroczenie limitu 500 elementów skutkuje błędem HTTP `400 Bad Request`.

### 4) Zalecenia wydajnościowe dla paczek

Choć system dopuszcza do 500 elementów w jednym żądaniu, rekomenduje się mniejsze paczki, ponieważ:

- skracają czas odpowiedzi,
- zmniejszają ryzyko timeoutów po stronie klienta, proxy lub API Gateway,
- ułatwiają obsługę ponowień w przypadku błędów częściowych.

---

## Publikacja/Aktualizacja umów `POST /agreements`

### 1) Endpoint

```http
POST /agreements
```

### 2) Opis działania

- Jeśli `agreementId` jest podany — aktualizacja istniejącej umowy.
- Jeśli `agreementId` nie jest podany — tworzenie nowej umowy.
- `numerPorzadkowy` służy do mapowania błędów w odpowiedzi.
- `externalSystemId` jest opcjonalnym identyfikatorem z systemu integratora.

### 3) Autoryzacja

Endpoint wymaga przekazania nagłówka:

```http
X-API-KEY: {twoj_klucz_api}
```

### 4) Przykład request

```json
[
  {
    "numerPorzadkowy": 1,
    "externalSystemId": "ABC/123",
    "komorkaWewnetrznaJsfp": "Wydział Zamówień Publicznych",
    "finansowanaZeSrodkow": true,
    "podstawoweDane": {
      "statusUmowy": "Aktywna",
      "numerUmowy": "02/16.10/92",
      "brakNumeruUmowy": false,
      "dataZawarciaUmowy": "20.08.2026"
    },
    "okresObowiazywania": {
      "umowaNaCzasNieoznaczony": false,
      "okresLiczba": 10,
      "okresJednostka": "dzień"
    },
    "szczegolyUmowy": {
      "przedmiotUmowy": "Zakup usług informatycznych",
      "wartoscPrzedmiotu": "2200.00",
      "opisWartosciPrzedmiotu": "Wartość zgodnie z ofertą wykonawcy."
    },
    "stronyUmowy": [
      {
        "rodzaj": "SU03",
        "regon": "551112229"
      },
      {
        "kraj": "PL",
        "rodzaj": "SU01",
        "nip": "1111111111",
        "czyKonsorcjum": false
      },
      {
        "kraj": "PL",
        "rodzaj": "SU03",
        "regon": "123456789",
        "czyKonsorcjum": false
      },
      {
        "kraj": "DE",
        "rodzaj": "SU01",
        "nazwa": "Example GmbH",
        "czyKonsorcjum": false,
        "daneAdresowe": {
          "ulica": "Hauptstrasse",
          "numerNieruchomosci": "10",
          "numerLokalu": "2",
          "miejscowosc": "Berlin",
          "kodPocztowy": "10115"
        }
      }
    ],
    "zmianyUmowy": [
      {
        "rodzajZmiany": "TSU02",
        "dataZmiany": "20.09.2026",
        "komentarz": "Aneks: aktualizacja terminu realizacji i doprecyzowanie zakresu usług."
      }
    ]
  }
]
```

> Uwaga: W przykładzie dla strony z Polski typu `SU01` przekazano wyłącznie `nip`. System pobierze z rejestru REGON brakujące dane, w tym `regon`, `nazwa` oraz adres, jeżeli nie został przekazany ręcznie.

### 5) Przykładowa odpowiedź

```json
{
  "message": "Wczytano 2 umów. Liczba elementów z błędami: 1",
  "successCount": 2,
  "errorCount": 1,
  "success": {
    "0": {
      "status": "CREATED",
      "message": "Umowa została utworzona.",
      "agreementId": "b6969777-f044-42de-ad29-5a298971c90d",
      "externalSystemId": "ABC/123"
    },
    "1": {
      "status": "UPDATED",
      "message": "Umowa została zaktualizowana.",
      "agreementId": "e2c2b4ea-3e9d-43b4-a17d-39c7772e450f",
      "externalSystemId": "CDE/456"
    }
  },
  "errors": {
    "2": {
      "status": "VALIDATION_ERROR",
      "message": "Wystąpiły błędy walidacji.",
      "fields": {
        "okresDo": "Pole jest wymagane."
      }
    }
  }
}
```

### 6) Zasada odpowiedzi 200

Dla `POST /agreements` system zwraca kod HTTP `200 OK`, nawet jeżeli część lub wszystkie elementy żądania zakończą się błędami biznesowymi lub walidacyjnymi.

Odpowiedź zawiera podsumowanie przetwarzania całej paczki, w tym:

- `successCount` — liczba poprawnie przetworzonych elementów,
- `errorCount` — liczba elementów zakończonych błędem,
- `success` — mapa poprawnie przetworzonych elementów,
- `errors` — mapa elementów zakończonych błędem.

Klient integracyjny powinien traktować odpowiedź `200 OK` jako potwierdzenie obsłużenia żądania przez API, natomiast wynik przetwarzania poszczególnych elementów powinien być odczytywany na podstawie pól `successCount`, `errorCount`, `success` oraz `errors`.

### 7) Kiedy pojawiają się kody 4xx/5xx

Kody `4xx/5xx` dotyczą błędów technicznych, np.:

- brak lub niepoprawny `X-API-KEY`,
- błędny format JSON,
- niepoprawne body żądania,
- błędy serwera.

W takich przypadkach odpowiedź nie ma postaci odpowiedzi zbiorczej z polami `success` i `errors`.

---

## Interpretacja pola `errors`

### Struktura kluczy w `errors`

- `errors["2"]` — błędy dotyczą elementu o `numerPorzadkowy = 2`.
- `errors["3"]` — błędy dotyczą elementu o `numerPorzadkowy = 3`.
- Klucz pusty `""` — błąd ogólny elementu, niezwiązany z żadnym konkretnym polem.
- Klucze typu `stronyUmowy[1].nip` — pełna ścieżka pola, które spowodowało błąd.

### Zakres i typy błędów w `errors`

Pole `errors` może zawierać:

#### Błędy pól

Przypisane do konkretnej ścieżki pola, np.:

```text
podstawoweDane.statusUmowy
```

#### Błędy elementów list

Ze wskazaniem indeksu elementu listy, np.:

```text
stronyUmowy[1].kraj
stronyUmowy[1].nip
stronyUmowy[1].regon
stronyUmowy[1].daneAdresowe
```

#### Błędy przekrojowe

Ogólne dla elementu, zwracane z pustym kluczem:

```json
{
  "": "Błąd ogólny"
}
```

### Przykład błędu dla strony z Polski bez `nip` i bez `regon`

Request — niepoprawna strona:

```json
{
  "kraj": "PL",
  "rodzaj": "SU03",
  "czyKonsorcjum": false
}
```

Response:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nip": "Dla strony umowy z Polski wymagane jest przekazanie numeru NIP albo REGON.",
    "stronyUmowy[1].regon": "Dla strony umowy z Polski wymagane jest przekazanie numeru NIP albo REGON."
  }
}
```

### Przykład błędu dla strony z Polski z jednocześnie przekazanym `nip` i `regon`

Request — niepoprawna strona:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "nip": "1111111111",
  "regon": "123456789",
  "czyKonsorcjum": false
}
```

Response:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nip": "Dla strony umowy z Polski należy przekazać tylko jeden identyfikator: NIP albo REGON.",
    "stronyUmowy[1].regon": "Dla strony umowy z Polski należy przekazać tylko jeden identyfikator: NIP albo REGON."
  }
}
```

### Przykład błędu dla strony z Polski z przekazaną nazwą

Request — niepoprawna strona:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "nip": "1111111111",
  "nazwa": "Przykładowa spółka",
  "czyKonsorcjum": false
}
```

Response:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nazwa": "Dla strony umowy z Polski nie należy przekazywać nazwy. Nazwa jest pobierana z rejestru REGON."
  }
}
```

### Przykład błędu dla strony spoza Polski z przekazanym `nip` albo `regon`

Request — niepoprawna strona:

```json
{
  "kraj": "DE",
  "rodzaj": "SU01",
  "nazwa": "Example GmbH",
  "nip": "1111111111",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Response:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nip": "Dla strony umowy spoza Polski nie należy przekazywać numeru REGON ani NIP."
  }
}
```

### Przykład błędu dla strony spoza Polski z `rodzaj = SU03`

Request — niepoprawna strona:

```json
{
  "kraj": "DE",
  "rodzaj": "SU03",
  "nazwa": "Example GmbH",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Response:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].rodzaj": "Dla strony umowy spoza Polski nie można wskazać rodzaju SU03 - JSFP."
  }
}
```

### Przykład błędu dla osoby fizycznej spoza Polski `SU02` z przekazanym `nazwa` i `daneAdresowe`

Request — niepoprawna strona:

```json
{
  "kraj": "DE",
  "rodzaj": "SU02",
  "imie": "Kristofus",
  "nazwisko": "Neuer",
  "nazwa": "Kristofus Neuer",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Response:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nazwa": "Dla osoby fizycznej spoza Polski pole 'nazwa' nie powinno być przekazywane.",
    "stronyUmowy[1].daneAdresowe": "Dla osoby fizycznej spoza Polski dane adresowe nie powinny być przekazywane."
  }
}
```

---

## Publikacja/Aktualizacja umów — walidacje biznesowe

Poniższe zasady opisują kluczowe walidacje biznesowe wykonywane dla każdego elementu żądania batch.

Naruszenie reguł biznesowych nie powoduje błędu HTTP — element zostaje oznaczony jako błędny w odpowiedzi w polu `errors`, a odpowiedź HTTP pozostaje `200 OK`.

### 1) Zasady ogólne przetwarzania elementu z listy żądania

- `numerPorzadkowy` jest wymagany i służy do mapowania błędów danego elementu w odpowiedzi `errors`.
- `agreementId`:
    - jeśli jest przekazany — przetwarzanie jako aktualizacja istniejącej umowy,
    - jeśli nie jest przekazany — przetwarzanie jako utworzenie nowej umowy.
- `externalSystemId` jest opcjonalnym identyfikatorem umowy po stronie systemu integratora.

### 2) Podstawowe dane umowy

- `statusUmowy` jest wymagany i musi przyjmować jedną z wartości dopuszczonych przez API.
- `dataZawarciaUmowy` jest wymagana i musi spełniać reguły poprawności określone w API.

Reguła spójności `numerUmowy` i `brakNumeruUmowy`:

- gdy `brakNumeruUmowy = true`, pole `numerUmowy` nie może być przekazane,
- gdy `brakNumeruUmowy = false`, pole `numerUmowy` jest wymagane.

### 3) Okres obowiązywania umowy

Sekcja `okresObowiazywania` podlega walidacji zależnej od pola `umowaNaCzasNieoznaczony`.

#### Umowa na czas nieoznaczony

Jeżeli `umowaNaCzasNieoznaczony = true`, pola:

- `okresLiczba`,
- `okresJednostka`,
- `okresOd`,
- `okresDo`

nie mogą być przekazane.

#### Umowa na czas oznaczony

Jeżeli `umowaNaCzasNieoznaczony = false`, wymagana jest jedna z par:

- `okresLiczba` i `okresJednostka`,
- `okresOd` i `okresDo`.

#### Walidacja zakresu dat

Jeżeli przekazane zostały pola `okresOd` oraz `okresDo`, muszą zostać spełnione następujące warunki:

- `okresOd` nie może być wcześniejsze niż `01.01.2026`,
- `okresOd` nie może być późniejsze niż 1 rok od dnia wysłania żądania,
- `okresDo` nie może być wcześniejsze niż `01.01.2026`,
- `okresDo` nie może być późniejsze niż `31.12.2500`,
- `okresDo` nie może być wcześniejsze niż `okresOd`.

### 4) Szczegóły umowy

- `przedmiotUmowy` podlega ograniczeniom długości zgodnie z OpenAPI.
- `wartoscPrzedmiotu`:
    - jest przekazywane w API jako tekst,
    - musi być równe lub większe od `0.00`,
    - nie może przekraczać `1000000000000.00`,
    - musi zawierać dokładnie dwa miejsca po separatorze dziesiętnym,
    - separatorem części dziesiętnej jest wyłącznie kropka `.`,
    - wartości bez części dziesiętnej nie są akceptowane.

Przykładowe poprawne wartości:

- `100.10`
- `1000.00`
- `0.05`

Przykładowe niepoprawne wartości:

- `100`
- `100.1`
- `100,10`
- `100.123`

### 5) Strony umowy

Każdy element listy `stronyUmowy` musi posiadać pole `rodzaj` i spełniać wymagania zależne od typu oraz kraju strony.

| Kod    | Typ strony     | Uwagi                                                                                                                                                                       |
|--------|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `SU01` | Przedsiębiorca | Dla kraju `PL` dane podmiotu są pobierane z rejestru REGON na podstawie `nip` albo `regon`. Dla kraju innego niż `PL` wymagane są `nazwa` i `daneAdresowe`.                 |
| `SU02` | Osoba fizyczna | Wymagane są dane osoby fizycznej zgodnie z OpenAPI. Dla osoby fizycznej nie należy przekazywać `nip`, `regon`, `nazwa` ani `daneAdresowe`. Wymagane są `imie` i `nazwisko`. |
| `SU03` | JSFP           | Dozwolone wyłącznie dla kraju `PL`. Dane są pobierane z rejestru REGON albo z bazy CRU w przypadku pierwszej strony umowy.                                                  |

Dodatkowo:

- `kraj` jest wymagany dla pozostałych stron umowy, czyli od `stronyUmowy[1]`;
- `czyKonsorcjum` jest wymagane dla pozostałych stron umowy, czyli od `stronyUmowy[1]`;
- pierwsza strona umowy `stronyUmowy[0]` jest traktowana specjalnie i nie powinna zawierać `kraj`, `czyKonsorcjum`, `nazwa`, `nip`, `daneAdresowe` ani `niejawnoscStrony`.

### 6) Walidacje pierwszej strony umowy `stronyUmowy[0]`

Pierwsza strona umowy reprezentuje jednostkę JSFP publikującą umowę.

Dla `stronyUmowy[0]` obowiązują następujące reguły:

| Pole               | Reguła                                                                                   |
|--------------------|------------------------------------------------------------------------------------------|
| `rodzaj`           | Wymagane. Musi mieć wartość `SU03`.                                                      |
| `regon`            | Wymagane. Na podstawie tego pola system pobiera dane jednostki z bazy CRU.               |
| `kraj`             | Nie należy przekazywać. Pole jest uzupełniane przez system jako `PL`.                    |
| `nazwa`            | Nie należy przekazywać. Pole jest uzupełniane przez system.                              |
| `nip`              | Nie należy przekazywać. Pole jest uzupełniane przez system.                              |
| `czyKonsorcjum`    | Nie należy przekazywać.                                                                  |
| `daneAdresowe`     | Nie należy przekazywać. Pole jest uzupełniane przez system.                              |
| `niejawnoscStrony` | Nie należy przekazywać. Jednostka wprowadzająca umowę nie może być wyłączona z jawności. |

Przykład poprawny:

```json
{
  "rodzaj": "SU03",
  "regon": "123456789"
}
```

Przykład niepoprawny:

```json
{
  "rodzaj": "SU03",
  "regon": "123456789",
  "nip": "1111111111",
  "kraj": "PL"
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[0].nip": "Dla pierwszej strony umowy nie należy przekazywać numeru NIP. Wymagany jest wyłącznie REGON."
  }
}
```

### 7) Walidacje pozostałych stron z Polski `stronyUmowy[1..n]`, `kraj = PL`

Dla pozostałych stron umowy z krajem `PL` obowiązują inne reguły niż dla pierwszej strony.

#### Wymagany dokładnie jeden identyfikator

Dla polskiej strony umowy typu `SU01` lub `SU03` należy przekazać dokładnie jeden identyfikator:

- `nip` albo
- `regon`.

Nie należy przekazywać obu identyfikatorów jednocześnie.

Nie należy również pomijać obu identyfikatorów.

Przykład poprawny — identyfikacja po NIP:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "nip": "1111111111",
  "czyKonsorcjum": false
}
```

Przykład poprawny — identyfikacja po REGON:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "regon": "123456789",
  "czyKonsorcjum": false
}
```

Przykład niepoprawny — brak obu identyfikatorów:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "czyKonsorcjum": false
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nip": "Dla strony umowy z Polski wymagane jest przekazanie numeru NIP albo REGON.",
    "stronyUmowy[1].regon": "Dla strony umowy z Polski wymagane jest przekazanie numeru NIP albo REGON."
  }
}
```

Przykład niepoprawny — przekazano oba identyfikatory:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "nip": "1111111111",
  "regon": "123456789",
  "czyKonsorcjum": false
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nip": "Dla strony umowy z Polski należy przekazać tylko jeden identyfikator: NIP albo REGON.",
    "stronyUmowy[1].regon": "Dla strony umowy z Polski należy przekazać tylko jeden identyfikator: NIP albo REGON."
  }
}
```

#### Pole `nazwa` dla stron z Polski

Dla stron z Polski typu `SU01` oraz `SU03` nie należy przekazywać pola `nazwa`.

Nazwa strony jest pobierana automatycznie z rejestru REGON na podstawie przekazanego `nip` albo `regon`.

Przykład niepoprawny:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "nip": "1111111111",
  "nazwa": "Przykładowa spółka",
  "czyKonsorcjum": false
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nazwa": "Dla strony umowy z Polski nie należy przekazywać nazwy. Nazwa jest pobierana z rejestru REGON."
  }
}
```

#### Dane adresowe dla polskiego przedsiębiorcy `SU01`

Dla strony z Polski typu `SU01` pole `daneAdresowe` jest opcjonalne.

Jeżeli `daneAdresowe` nie zostanie przekazane, system pobierze adres z rejestru REGON.

Jeżeli `daneAdresowe` zostanie przekazane ręcznie, musi być kompletne.

Za kompletne dane adresowe uznaje się uzupełnienie co najmniej pól:

- `miejscowosc`
- `kodPocztowy`
- `wojewodztwo`
- `powiat`
- `gminaMiastoDzielnica`
- `numerNieruchomosci`

Przykład poprawny — adres nieprzekazany, zostanie pobrany z REGON:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "nip": "1111111111",
  "czyKonsorcjum": false
}
```

Przykład poprawny — adres przekazany ręcznie i kompletny:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "regon": "123456789",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "ulica": "Puławska",
    "numerNieruchomosci": "33",
    "numerLokalu": "5",
    "wojewodztwo": "mazowieckie",
    "powiat": "piaseczyński",
    "gminaMiastoDzielnica": "Piaseczno",
    "miejscowosc": "Piaseczno",
    "kodPocztowy": "05-500"
  }
}
```

Przykład niepoprawny — adres niekompletny:

```json
{
  "kraj": "PL",
  "rodzaj": "SU01",
  "regon": "123456789",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Piaseczno",
    "kodPocztowy": "05-500"
  }
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].daneAdresowe.wojewodztwo": "Jeżeli dla strony umowy z Polski przekazano dane adresowe ręcznie, należy uzupełnić komplet wymaganych pól adresowych.",
    "stronyUmowy[1].daneAdresowe.powiat": "Jeżeli dla strony umowy z Polski przekazano dane adresowe ręcznie, należy uzupełnić komplet wymaganych pól adresowych.",
    "stronyUmowy[1].daneAdresowe.gminaMiastoDzielnica": "Jeżeli dla strony umowy z Polski przekazano dane adresowe ręcznie, należy uzupełnić komplet wymaganych pól adresowych.",
    "stronyUmowy[1].daneAdresowe.numerNieruchomosci": "Jeżeli dla strony umowy z Polski przekazano dane adresowe ręcznie, należy uzupełnić komplet wymaganych pól adresowych."
  }
}
```

#### Dane adresowe dla polskiej JSFP `SU03`

Dla strony z Polski typu `SU03` nie należy przekazywać pola `daneAdresowe`.

Adres jest pobierany automatycznie z rejestru REGON.

Przykład poprawny:

```json
{
  "kraj": "PL",
  "rodzaj": "SU03",
  "regon": "123456789",
  "czyKonsorcjum": false
}
```

Przykład niepoprawny:

```json
{
  "kraj": "PL",
  "rodzaj": "SU03",
  "regon": "123456789",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Warszawa",
    "kodPocztowy": "00-001",
    "numerNieruchomosci": "1"
  }
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].daneAdresowe": "Dla strony umowy typu JSFP nie można przekazywać danych adresowych. Adres jest pobierany z rejestru REGON."
  }
}
```

### 8) Walidacje stron spoza Polski `kraj != PL`

Dla stron umowy spoza Polski obowiązują następujące reguły:

#### Zakaz przekazywania `nip` i `regon`

Dla strony umowy spoza Polski nie należy przekazywać numerów:

- `nip`
- `regon`

Przykład niepoprawny:

```json
{
  "kraj": "DE",
  "rodzaj": "SU01",
  "nazwa": "Example GmbH",
  "nip": "1111111111",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nip": "Dla strony umowy spoza Polski nie należy przekazywać numeru REGON ani NIP."
  }
}
```

#### Zakaz przekazywania `SU03` dla kraju innego niż `PL`

Rodzaj `SU03` jest dozwolony wyłącznie dla stron z Polski.

Przykład niepoprawny:

```json
{
  "kraj": "DE",
  "rodzaj": "SU03",
  "nazwa": "Example GmbH",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].rodzaj": "Dla strony umowy spoza Polski nie można wskazać rodzaju SU03 - JSFP."
  }
}
```

#### Strona spoza Polski typu `SU02` — osoba fizyczna

Dla strony umowy spoza Polski typu `SU02` wymagane są dane osoby fizycznej.

Wymagane pola:

- `kraj`
- `rodzaj`
- `czyKonsorcjum`
- `imie`
- `nazwisko`

Dla osoby fizycznej spoza Polski nie należy przekazywać pól:

- `nazwa`
- `daneAdresowe`
- `nip`
- `regon`

Przykład poprawny:

```json
{
  "kraj": "DE",
  "rodzaj": "SU02",
  "imie": "Kristofus",
  "nazwisko": "Neuer",
  "czyKonsorcjum": false
}
```

Przykład niepoprawny — przekazano `nazwa` i `daneAdresowe`:

```json
{
  "kraj": "DE",
  "rodzaj": "SU02",
  "imie": "Kristofus",
  "nazwisko": "Neuer",
  "nazwa": "Kristofus Neuer",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nazwa": "Dla osoby fizycznej spoza Polski pole 'nazwa' nie powinno być przekazywane.",
    "stronyUmowy[1].daneAdresowe": "Dla osoby fizycznej spoza Polski dane adresowe nie powinny być przekazywane."
  }
}
```

Przykład niepoprawny — brak `imie` i `nazwisko`:

```json
{
  "kraj": "DE",
  "rodzaj": "SU02",
  "czyKonsorcjum": false
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].imie": "Dla osoby fizycznej spoza Polski pole 'imie' jest wymagane.",
    "stronyUmowy[1].nazwisko": "Dla osoby fizycznej spoza Polski pole 'nazwisko' jest wymagane."
  }
}
```

#### Wymagane pole `nazwa`

Dla strony umowy spoza Polski typu `SU01` pole `nazwa` jest wymagane.

Przykład niepoprawny:

```json
{
  "kraj": "DE",
  "rodzaj": "SU01",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115",
    "numerNieruchomosci": "10"
  }
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].nazwa": "Dla strony umowy spoza Polski pole 'nazwa' jest wymagane."
  }
}
```

#### Wymagane `daneAdresowe`

Dla strony umowy spoza Polski typu `SU01` pole `daneAdresowe` jest wymagane.

Przykład niepoprawny:

```json
{
  "kraj": "DE",
  "rodzaj": "SU01",
  "nazwa": "Example GmbH",
  "czyKonsorcjum": false
}
```

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].daneAdresowe": "Dla strony umowy spoza Polski dane adresowe są wymagane."
  }
}
```

### Dane adresowe dla stron spoza Polski

Dla stron umowy spoza Polski typu `SU01` pole `daneAdresowe` jest wymagane, ale zakres przyjmowanych pól adresowych jest ograniczony.

Dla strony spoza Polski w obiekcie `daneAdresowe` można przekazać wyłącznie:

- `ulica`,
- `numerNieruchomosci`,
- `numerLokalu`,
- `kodPocztowy`,
- `miejscowosc`.

Pola wymagane:

- `numerNieruchomosci`,
- `kodPocztowy`,
- `miejscowosc`.

Pola opcjonalne:

- `ulica`,
- `numerLokalu`.

Nie należy przekazywać pól właściwych dla adresów krajowych, takich jak:

- `wojewodztwo`,
- `powiat`,
- `gminaMiastoDzielnica`.

Przekazanie niedozwolonych pól adresowych dla strony spoza Polski skutkuje błędem walidacji przypisanym do konkretnego pola, np. `stronyUmowy[1].daneAdresowe.wojewodztwo`.

Przykład poprawny:

```json
{
  "kraj": "DE",
  "rodzaj": "SU01",
  "nazwa": "Example GmbH",
  "czyKonsorcjum": false,
  "daneAdresowe": {
    "numerNieruchomosci": "10",
    "numerLokalu": "2",
    "miejscowosc": "Berlin",
    "kodPocztowy": "10115"
  }
}
```

### 9) Walidacje danych pobieranych z rejestru REGON

Dla stron z Polski typu `SU01` i `SU03` system pobiera dane z rejestru REGON na podstawie przekazanego `nip` albo `regon`.

#### Brak podmiotu w rejestrze REGON

Jeżeli dla przekazanego identyfikatora nie odnaleziono podmiotu, element zostanie oznaczony błędem.

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].regon": "Nie znaleziono podmiotu w rejestrze REGON dla identyfikatora: 123456789"
  }
}
```

#### Więcej niż jeden wynik w rejestrze REGON

- Brak pola `typDzialalnosci`

Jeżeli dla przekazanego identyfikatora (REGON lub NIP) rejestr REGON zwróci więcej niż jeden podmiot, a pole `typDzialalnosci` nie zostanie przekazane, API zwróci błąd.

W takim przypadku integrator powinien ponowić żądanie, wskazując w polu `typDzialalnosci` właściwy typ działalności strony umowy. Dostępne typy zostaną podane w komunikacie błędu.

Przykładowy błąd:

```json
{
  "status": "CONFLICT",
  "message": "Nie znaleziono podmiotu dla wskazanego typu działalności.",
  "fields": {
    "stronyUmowy[1].nip": "Dla podanego numeru NIP znaleziono więcej niż jeden podmiot w rejestrze REGON. Należy wskazać właściwy typ działalności w polu 'typDzialalnosci'. Dostępne typy dla tego numeru NIP: [CEIDG, OTHER]."
  }
}
```

- Nieprawidłowa wartość pola `typDzialalnosci`

Jeżeli integrator przekaże wartość inną niż `CEIDG`, `AGRICULTURAL` lub `OTHER`, żądanie nie przejdzie walidacji. Taka wartość nie jest przekazywana do wyszukania w rejestrze REGON.

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].typDzialalnosci": "Dozwolone wartości pola to: [CEIDG, AGRICULTURAL, OTHER]."
  }
}
```

- Typ działalności niezgodny z wynikiem wyszukiwania

Jeżeli integrator przekaże poprawną wartość pola `typDzialalnosci` (np. `CEIDG`, `AGRICULTURAL` lub `OTHER`), ale dla wskazanego numeru REGON lub NIP nie występuje podmiot o tym typie działalności, API zwróci błąd `CONFLICT`.

Komunikat błędu będzie zawierał typy działalności faktycznie dostępne dla danego identyfikatora.

Przykładowy błąd:

```json
{
  "status": "CONFLICT",
  "message": "Nie znaleziono podmiotu dla wskazanego typu działalności.",
  "fields": {
    "stronyUmowy[1].nip": "Nie znaleziono podmiotu w rejestrze REGON dla podanej kombinacji numeru NIP oraz typu działalności. Dostępne typy dla tego numeru NIP: [AGRICULTURAL]."
  }
}
```

#### Niepoprawny format identyfikatora

Jeżeli rejestr REGON odrzuci przekazany identyfikator, np. z powodu niepoprawnej długości lub formatu, komunikat zostanie przypisany do pola `nip` albo `regon`.

Przykładowy błąd:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].regon": "REGON musi zawierać 9 lub 14 cyfr."
  }
}
```

### 10) Wyłączenie jawności strony

Jeżeli w stronie umowy przekazano `niejawnoscStrony`, to nie wolno przekazywać dodatkowych danych strony poza polami obowiązkowymi.

W takim przypadku dopuszczalne są wyłącznie pola:

- `kraj`,
- `rodzaj`,
- `czyKonsorcjum`,
- `niejawnoscStrony`.

Próba przesłania dodatkowych danych, np. `nazwa`, `regon`, `nip`, `daneAdresowe`, `imie`, `nazwisko`, spowoduje błąd biznesowy w `errors`.

Przykład błędu:

```json
{
  "status": "VALIDATION_ERROR",
  "message": "Wystąpiły błędy walidacji.",
  "fields": {
    "stronyUmowy[1].niejawnoscStrony": "Gdy 'niejawnoscStrony' jest określona, zakres danych strony ogranicza się do pól obowiązkowych: 'kraj', 'rodzaj', 'czyKonsorcjum'."
  }
}
```

### 11) Jawność danych

W API występują pola opisujące wyłączenie jawności danych, np.:

- `niejawnoscStrony`,
- `niejawnoscPrzedmiotu`,
- `niejawnoscWartosciPrzedmiotu`.

Gdy przekazano obiekt `niejawnosc`, jego pola muszą być kompletne zgodnie z OpenAPI.

Jeżeli `podstawa = INNA`, pole `komentarz` jest wymagane.

Jeżeli `podstawa != INNA`, pole `komentarz` nie powinno być przekazywane.

### 12) Zmiany umowy

Jeżeli przekazywana jest lista `zmianyUmowy`, to dla każdego elementu zmiany:

- `rodzajZmiany` jest wymagany,
- `dataZmiany` jest wymagana,
- `komentarz` jest wymagany.

> Ważne: Lista zmianyUmowy musi zawierać wszystkie zmiany umowy, które mają zostać zapisane w systemie.

Podczas aktualizacji umowy lista zmian jest nadpisywana w całości, a nie uzupełniana o nowe elementy.

Oznacza to, że:

Jeżeli umowa posiada 3 zapisane zmiany, a podczas aktualizacji przez API zostanie przekazana lista zawierająca tylko 1
zmianę, w systemie pozostanie wyłącznie ta 1 zmiana. Pozostałe 2 zostaną usunięte.

Aby zachować wszystkie dotychczasowe zmiany i dodać kolejną, należy przekazać pełną listę zawierającą zarówno
wcześniejsze, jak i nową zmianę.

> Uwaga: API nie weryfikuje kompletności przekazanej listy względem wcześniej zapisanych zmian. Odpowiedzialność za
> przekazanie pełnej listy zmianyUmowy spoczywa na systemie integrującym się.

### 13) Walidacja znaków HTML w polach tekstowych

W polach tekstowych wprowadzono walidację ograniczającą możliwość przekazywania treści zawierających elementy HTML/XML.

Walidacja odrzuca wartości zawierające w szczególności:

- znaczniki HTML/XML, np. `<tag>`, `</tag>`,
- encje HTML, np. `&lt;`, `&gt;`, `&amp;`,
- pojedyncze znaki `<` lub `>`.

---

## Wycofanie umów z publikacji `POST /withdraw`

Endpoint umożliwia wsadowe wycofanie opublikowanych umów z publikacji w systemie CRU.

### 1) Endpoint

```http
POST /withdraw
```
### 2) Opis działania

Endpoint służy do wycofania z publikacji jednej lub wielu umów wskazanych przez `agreementId`.

Dla każdego elementu żądania system:

- wyszukuje umowę po `agreementId`,
- weryfikuje możliwość wykonania operacji wycofania,
- ustawia status procesowy umowy na `Wycofana z publikacji`,
- zapisuje przekazany `komentarz` jako przyczynę wycofania z publikacji.

Każdy element listy żądania jest przetwarzany niezależnie. Oznacza to, że błąd dla jednej umowy nie blokuje przetwarzania pozostałych elementów paczki.

### 3) Autoryzacja

Endpoint wymaga przekazania nagłówka:

```http
X-API-KEY: {twoj_klucz_api}
```

Do wywołania endpointu wymagane są uprawnienia użytkownika posiadającego rolę Publikującego.

### 4) Przykład request
```json
{
  "umowy": [
    {
      "agreementId": "b6969777-f044-42de-ad29-5a298971c90d",
      "komentarz": "Wycofanie umowy z publikacji na wniosek jednostki."
    },
    {
      "agreementId": "e2c2b4ea-3e9d-43b4-a17d-39c7772e450f",
      "komentarz": "Błędna publikacja — umowa zostanie opublikowana ponownie po korekcie danych."
    }
  ]
}
```

### 5) Przykładowa odpowiedź
```json
{
  "message": "Wycofane umowy: 2. Liczba elementów z błędami: 0",
  "successCount": 2,
  "errorCount": 0,
  "success": {
    "0": {
      "status": "UPDATED",
      "message": "Umowa została wycofana z publikacji.",
      "agreementId": "b6969777-f044-42de-ad29-5a298971c90d"
    },
    "1": {
      "status": "UPDATED",
      "message": "Umowa została wycofana z publikacji.",
      "agreementId": "e2c2b4ea-3e9d-43b4-a17d-39c7772e450f"
    }
  },
  "errors": {}
}
```

### 6) Zasada odpowiedzi 200

Dla POST /withdraw system zwraca kod HTTP 200 OK, nawet jeżeli część elementów żądania zakończy się błędami biznesowymi lub walidacyjnymi.

Odpowiedź zawiera podsumowanie przetwarzania całej paczki, w tym:

`successCount` — liczbę poprawnie przetworzonych elementów,
`errorCount` — liczbę elementów zakończonych błędem,
`success` — mapę elementów zakończonych sukcesem,
`errors` — mapę elementów zakończonych błędem.

Klient integracyjny powinien interpretować odpowiedź 200 OK jako potwierdzenie obsłużenia żądania przez API, natomiast wynik przetwarzania poszczególnych elementów należy odczytywać na podstawie pól `success`, `errors`, `successCount` i `errorCount`.

### 7) Kiedy pojawiają się kody 4xx/5xx

Kody 4xx/5xx dotyczą błędów technicznych, np.:

- brak lub niepoprawny X-API-KEY,
- błędny format JSON,
- niepoprawne body żądania,
- błędy serwera.

W takich przypadkach odpowiedź nie ma postaci odpowiedzi zbiorczej.

### 8) Walidacje biznesowe endpointu POST /withdraw

Dla każdego elementu listy żądania wykonywane są walidacje biznesowe.

Umowa musi istnieć

Jeżeli dla przekazanego `agreementId` nie odnaleziono umowy, element zostanie oznaczony błędem.

Przykładowy błąd:

```json
{
  "status": "NOT_EXISTS",
  "message": "Nie znaleziono umowy."
}
```

- Wycofanie możliwe tylko dla umowy opublikowanej.
- Wycofanie z publikacji jest możliwe wyłącznie wtedy, gdy umowa znajduje się w statusie procesowym `Opublikowana`.
- Jeżeli umowa znajduje się w innym statusie, element zostanie oznaczony błędem biznesowym.
- Wycofanie nie jest możliwe, gdy trwa proces zmiany danych
- Jeżeli dla umowy istnieje rozpoczęty proces zmiany danych, wycofanie z publikacji nie jest możliwe.
  W takim przypadku element zostanie oznaczony błędem biznesowym.

### 10) Uwagi integracyjne
- endpoint służy wyłącznie do wycofania z publikacji już istniejących umów,
- operacja nie tworzy nowej wersji umowy i nie służy do aktualizacji jej danych,
- po wycofaniu umowa przechodzi do statusu `Wycofana z publikacji`.

---

## Pobranie szczegółów umowy `GET /{agreementId}`

Endpoint służy do pobrania szczegółów umowy na podstawie identyfikatora umowy.

### 1) Endpoint

```http
GET /{agreementId}
```

### 2) Autoryzacja

Endpoint wymaga przekazania nagłówka:

```http
X-API-KEY: {twoj_klucz_api}
```

### 3) Przykład curl

```bash
curl -X GET \
https://jsfp-cru-test.mf.gov.pl/v1/api/publish/eb72ae52-7e09-471c-8e1e-deb5f75f4a06 \
-H "X-API-KEY: YOUR_API_KEY"
```

### 4) Parametry

- `agreementId` — identyfikator umowy w systemie CRU.

> Uwaga: Identyfikator wewnętrzny umowy jest wymagany do pobrania danych, ponieważ umowa może nie posiadać własnego numeru umowy.

---

## Lista streszczeń umów `GET /summary`

Endpoint umożliwia pobranie listy streszczeń umów z zastosowaniem filtrowania, sortowania oraz stronicowania wyników.

### 1) Endpoint

```http
GET /summary
```

### 2) Autoryzacja

Endpoint wymaga przekazania nagłówka:

```http
X-API-KEY: {twoj_klucz_api}
```

### 3) Przykład curl

```bash
curl -X GET \
"https://jsfp-cru-test.mf.gov.pl/v1/api/publish/summary?offset=0&limit=20" \
-H "X-API-KEY: YOUR_API_KEY"
```

### 4) Parametry filtrowania

Obsługiwane filtry:

- `numerUmowy`,
- `przedmiotUmowy`,
- `agreementIds`,
- `externalSystemIds`,
- `dataZawarciaUmowyOd`,
- `dataZawarciaUmowyDo`.

#### Filtrowanie po numerze umowy

Jeżeli podano parametr `numerUmowy`, wynik jest zawężany do rekordów, których numer zawiera podany fragment.

#### Filtrowanie po przedmiocie umowy

Jeżeli podano parametr `przedmiotUmowy`, wynik jest zawężany do rekordów, których przedmiot zawiera podany fragment.

#### Filtrowanie po identyfikatorach wewnętrznych

Jeżeli podano parametr `agreementIds`, wynik jest zawężany do umów o wskazanych identyfikatorach wewnętrznych.

#### Filtrowanie po identyfikatorach zewnętrznych

Jeżeli podano parametr `externalSystemIds`, wynik jest zawężany do umów powiązanych z podanymi identyfikatorami zewnętrznymi.

Przykład:

```http
GET /summary?externalSystemIds=EXT-001,EXT-002
```

#### Filtrowanie po dacie zawarcia umowy

Parametry `dataZawarciaUmowyOd` oraz `dataZawarciaUmowyDo` są traktowane jako opcjonalny zakres daty zawarcia umowy.

Filtry łączone są operatorem `AND`.

### 5) Paginacja

| Parametr        | Opis                                      |
|-----------------|-------------------------------------------|
| `offset`        | indeks pierwszego rekordu, domyślnie `0`  |
| `limit`         | liczba rekordów na stronę, domyślnie `20` |
| `sortDirection` | `ASC` albo `DESC`                         |

### 6) Przykładowa odpowiedź

```json
{
  "content": [
    {
      "numerUmowy": "UM/2026/001",
      "brakNumeruUmowy": false,
      "numerSystemowy": 123456789,
      "statusProcesowy": "Opublikowana",
      "przedmiotUmowy": "Zakup usług informatycznych",
      "dataZawarciaUmowy": "09.06.2026",
      "dataOstatniejModyfikacjiUmowy": "09.06.2026",
      "agreementId": "550e8400-e29b-41d4-a716-446655440000",
      "externalSystemId": "EXT-001"
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 20
}
```

>Uwaga:
> **Wykluczenie umów w statusie `Robocza`**.
>- Wyniki zawsze pomijają umowy w statusie roboczym. Dzięki temu na liście nie pojawiają się rekordy będące w trakcie przygotowania i niegotowe do dalszego procesowania.

---

## Lista statusów umów (GET)

Endpoint umożliwia masową weryfikację istnienia umów w systemie CRU na podstawie identyfikatorów umów lub identyfikatorów systemów zewnętrznych.

### 1) Endpoint

```
GET /status
```

### 2) Autoryzacja
Endpoint wymaga przekazania nagłówka:
```
X-API-KEY: {twoj_klucz_api}
```

### 3) Przykład (curl)

```bash
curl -X GET \
"https://jsfp-cru-test.mf.gov.pl/v1/api/publish/status?externalSystemIds=1/100,2222/22" \
-H "X-API-KEY: YOUR_API_KEY"
```

### 4) Parametry

Co najmniej jeden z poniższych parametrów jest wymagany:

`agreementIds` – lista identyfikatorów umów w systemie CRU (UUID),
`externalSystemIds` – lista identyfikatorów zewnętrznych.

Możliwe jest przekazanie obu parametrów jednocześnie.

Dla każdego przekazanego identyfikatora zwracana jest osobna pozycja w odpowiedzi.

Uwaga: Endpoint nie służy do filtrowania ani wyszukiwania listy umów. Zwraca wyłącznie informację o istnieniu wskazanych identyfikatorów.

### 5) Paginacja

| Parametr   | Opis                                     |
|------------|------------------------------------------|
| **offset** | indeks pierwszego rekordu (domyślnie 0)  |
| **limit**  | liczba rekordów na stronę (domyślnie 20) |

### 6) Przykładowa odpowiedź

```json
{
  "content": [
    {
      "agreementId": "c59cdd10-1691-44b6-812d-529ad0173cbe",
      "externalSystemId": "1/100",
      "status": "ALREADY_EXISTS",
      "message": "Taka umowa już istnieje w systemie."
    },
    {
      "externalSystemId": "2222/22",
      "status": "NOT_EXISTS",
      "message": "Nie znaleziono umowy dla podanego identyfikatora."
    }
  ],
  "total": 2,
  "offset": 0,
  "limit": 20
}
```

### 7) Znaczenie statusów
- `ALREADY_EXISTS` - umowa została odnaleziona w systemie,
- `NOT_EXISTS` - nie odnaleziono umowy dla wskazanego identyfikatora.

### 8) Dodatkowe informacje

Jeżeli umowa zostanie odnaleziona:

przy wyszukiwaniu po `agreementId` odpowiedź może zawierać również powiązany `externalSystemId`,
przy wyszukiwaniu po `externalSystemId` odpowiedź może zawierać również powiązany `agreementId`.

Pole total oznacza liczbę wszystkich przekazanych identyfikatorów uwzględnionych w odpowiedzi.

---

## Obsługa błędów

API zwraca standardowe kody HTTP dla błędów technicznych:

| Kod   | Znaczenie                                  |
|-------|--------------------------------------------|
| `400` | Błędne dane wejściowe                      |
| `403` | Brak uprawnień lub niepoprawny `X-API-KEY` |
| `404` | Nie znaleziono zasobu                      |
| `429` | Przekroczono limit wywołań                 |
| `500` | Błąd serwera                               |

### 1) Struktura błędu technicznego

```json
{
  "code": "JSON_PARSE_ERROR",
  "message": "Niepoprawny format JSON.",
  "details": {
    "": "JSON parse error"
  }
}
```

---

## Zakres obsługiwanych statusów umów w API

### 1) Publikacja / aktualizacja / wycofanie umów

Możliwa jest publikacja lub aktualizacja danych umowy przez endpoint `POST /agreements` dla umów w statusie:

- **Opublikowana** — wyłącznie w przypadku, gdy dla umowy nie zostały rozpoczęte zmiany.

Możliwe jest wycofanie umowy z publikacji przez endpoint `POST /withdraw` dla umów w statusie:

- **Opublikowana** — wyłącznie w przypadku, gdy dla umowy nie zostały rozpoczęte zmiany.

> Uwaga: jeżeli dla umowy istnieją rozpoczęte zmiany, aktualizacja przez API nie będzie możliwa.

### 2) Pobieranie listy i szczegółów umów przez API

Możliwe jest wyświetlenie listy oraz pobieranie szczegółów umów dla umów w statusach:

- **Przekazana do publikacji**
- **Usunięta przed publikacją**
- **Weryfikowana**
- **Opublikowana**
- **Wycofana z publikacji**

---

## Słowniki i kody w API

### 1) Rodzaje zmian umowy `rodzajZmiany`

| Nazwa                                        | Kod     |
|----------------------------------------------|---------|
| Korekta danych                               | `TSU01` |
| Aneks do umowy                               | `TSU02` |
| Zmiana w zakresie wyłączenia jawności danych | `TSU03` |
| Zmiana danych strony umowy                   | `TSU04` |
| Rozwiązanie umowy                            | `TSU05` |
| Wypowiedzenie umowy                          | `TSU06` |
| Odstąpienie od umowy                         | `TSU07` |
| Wygaśnięcie umowy                            | `TSU10` |
| Cesja umowy                                  | `TSU11` |
| Inne                                         | `inne`  |

### 2) Rodzaje stron umowy `rodzaj`

| Nazwa          | Kod    |
|----------------|--------|
| Przedsiębiorca | `SU01` |
| Osoba fizyczna | `SU02` |
| JSFP           | `SU03` |

### 3) Zakres wyłączenia jawności `zakres`

| Nazwa             | Kod    |
|-------------------|--------|
| Dane strony umowy | `SC02` |
| Przedmiot umowy   | `SC03` |
| Wartość umowy     | `SC04` |

### 4) Podstawa wyłączenia jawności `podstawa`

| Kod            | Opis                                                      |
|----------------|-----------------------------------------------------------|
| `ART_5_UST_1`  | Art. 5 ust. 1 ustawy o dostępie do informacji publicznej  |
| `ART_5_UST_2`  | Art. 5 ust. 2 ustawy o dostępie do informacji publicznej  |
| `ART_5_UST_2A` | Art. 5 ust. 2a ustawy o dostępie do informacji publicznej |
| `ART_5_UST_2B` | Art. 5 ust. 2b ustawy o dostępie do informacji publicznej |
| `INNA`         | Inna podstawa prawna                                      |

> Uwaga: Gdy `podstawa = INNA`, mogą obowiązywać dodatkowe reguły walidacyjne, np. wymagany komentarz.

---

## Walidacja treści pól tekstowych

Pola tekstowe przekazywane przez API nie mogą zawierać znaczników HTML/XML, skryptów ani treści mogących zostać zinterpretowanych jako kod wykonywalny.

W przypadku wykrycia niedozwolonej treści żądanie zostanie odrzucone z błędem walidacji.

Dane poprawnie przyjęte przez API są zapisywane w postaci zgodnej z wartością przekazaną w żądaniu.

Przykładowy komunikat walidacyjny:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Przekazane dane zawierają niedozwoloną treść HTML/JS.",
  "details": {
    "$[0].szczegolyUmowy.przedmiotUmowy": "Wartość pola nie może zawierać znaczników HTML/XML ani treści mogących zostać zinterpretowanych jako kod wykonywalny."
  }
}
```

---

## Dobre praktyki integracyjne

- Przechowuj `agreementId` jako główny identyfikator umowy.
- Jeżeli korzystasz z własnego identyfikatora, przekazuj go w polu `externalSystemId`.
- Wysyłaj dane wsadowo w paczkach po 100–200 elementów.
- Nie wykonuj równoległych wywołań `POST /agreements` dla tego samego `X-API-KEY`.
- Obsługuj wynik każdego elementu na podstawie map `success` i `errors`.
- Dla stron z Polski przekazuj dokładnie jeden identyfikator: `nip` albo `regon`.
- Dla stron spoza Polski nie przekazuj `nip` ani `regon`.
- Dla osoby fizycznej spoza Polski typu `SU02` przekazuj `imie` i `nazwisko`; nie przekazuj `nazwa` ani `daneAdresowe`.
- Dla pierwszej strony umowy przekazuj wyłącznie `rodzaj = SU03` oraz `regon`.
- Nie przekazuj pola `nazwa` dla stron z Polski typu `SU01` i `SU03`, ponieważ nazwa jest pobierana z rejestru REGON.
- Nie przekazuj pola `daneAdresowe` dla strony z Polski typu `SU03`, ponieważ adres jest pobierany z rejestru REGON.
