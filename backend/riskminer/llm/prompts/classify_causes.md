---
version: 1
alias: bulk
output: CauseBatch
---
Klasyfikujesz przyczyny zmian umów o roboty wodno-kanalizacyjne (ogłoszenia BZP o zmianie umowy i o wykonaniu umowy).
Każda pozycja to <item id="...">Przyczyna: ...  Opis zmiany: ...</item>. Dla każdej pozycji wybierz kod przyczyny
ŹRÓDŁOWEJ (dlaczego doszło do zmiany), nie skutku (co zmieniono).

Kody:
$labels

Zasady:
1. R07 tylko wtedy, gdy tekst mówi o robotach dodatkowych lub zamiennych, ale nie podaje ich przyczyny. Gdy podaje
   (np. nieznane sieci w ziemi, zły grunt, błąd projektu, decyzja gestora), wybierz kod tej przyczyny.
2. N-UNSPEC, gdy tekst nie podaje żadnej przyczyny (tylko podstawa prawna, "zgodnie z art. 455" albo sam skutek).
3. secondary tylko wtedy, gdy tekst wyraźnie wskazuje drugą, inną przyczynę; inaczej null.
4. quote = dosłowny fragment tekstu tej pozycji (maks. 120 znaków), który uzasadnia wybór kodu, bez zmian.
5. confidence od 0 do 1: jak pewny jesteś kodu primary.
6. Zwróć każdą pozycję dokładnie raz, z tym samym id.
$examples
