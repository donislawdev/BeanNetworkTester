# Bean Network Tester 🫘 - symulator złych warunków sieciowych (Windows)

[![CI](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml/badge.svg)](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/donislawdev/BeanNetworkTester?sort=semver)](https://github.com/donislawdev/BeanNetworkTester/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/donislawdev/BeanNetworkTester/total)](https://github.com/donislawdev/BeanNetworkTester/releases)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)

Narzędzie dla testerów i deweloperów: sprawdź, jak aplikacja zachowuje się przy słabym
internecie. Przechwytuje ruch sieciowy sterownikiem **[WinDivert](https://www.reqrypt.org/windivert.html)** (jak Clumsy / NetLimiter)
i pozwala go kontrolowanie „psuć” - dodać ping, gubić pakiety, ograniczyć prędkość, zrywać
połączenia itd. Nazywa się **Bean Network Tester** i ma czytelny interfejs okienkowy z podpowiedziami oraz tryb wiersza poleceń do CI.

**Spis treści**

- [Dla niecierpliwych (3 kroki)](#dla-niecierpliwych-3-kroki)
- [Język / Language](#język--language)
- [Wymagania](#wymagania)
- [Okno programu](#okno-programu)
- [Opis wszystkich opcji](#opis-wszystkich-opcji)
- [Składnia filtrów (proces / IP / port)](#składnia-filtrów-proces--ip--port)
- [Statystyki (co znaczą liczniki)](#statystyki-co-znaczą-liczniki)
- [Plik konfiguracji (wspólny GUI + CLI)](#plik-konfiguracji-wspólny-gui--cli)
- [Tryb wiersza poleceń (CLI)](#tryb-wiersza-poleceń-cli)
- [Przepisy pod CI/CD](#przepisy-pod-cicd)
- [Zbudowanie pliku .exe](#zbudowanie-pliku-exe)
- [Co może zaskoczyć (przeczytaj, zanim zgłosisz błąd)](#co-może-zaskoczyć-przeczytaj-zanim-zgłosisz-błąd)
- [Testy](#testy)
- [Struktura projektu](#struktura-projektu)
- [Jak to działa (skrót)](#jak-to-działa-skrót)
- [Uwagi i ograniczenia](#uwagi-i-ograniczenia)
- [Współtworzenie](#współtworzenie)
- [Wsparcie projektu](#wsparcie-projektu)
- [Autor](#autor)
- [Licencja](#licencja)
- [Komponenty firm trzecich](#komponenty-firm-trzecich)
- [Prywatność: brak telemetrii](#prywatność-brak-telemetrii)
- [Uwaga: SmartScreen i antywirusy](#uwaga-smartscreen-i-antywirusy)

## Dla niecierpliwych (3 kroki)

1. Pobierz `BeanNetworkTester` (albo zbuduj: `pyinstaller --noconfirm BeanNetworkTester.spec`).
2. Uruchom `BeanNetworkTester.exe` - program **sam poprosi o uprawnienia administratora**
   (są potrzebne sterownikowi WinDivert). Z repozytorium: `python bean_network_tester.py`.
3. Wybierz preset z listy „Profile” (np. „Sieci 3G”) i kliknij **START**.

To **ten sam plik** obsługuje tryb tekstowy: `BeanNetworkTester.exe --simulate --loss 10 --duration 5`.

U góry okna pasek „Aktywne: …” po polsku podsumowuje, co właśnie robisz
(np. *Aktywne: +150 ms pingu, 1% strat, pobieranie ≤ 384 KB/s*). Po najechaniu myszą na
dowolne pole pojawia się dymek z wyjaśnieniem, co ono robi.

> Uwaga: samo wybranie presetu tylko wypełnia pola - zakłócenia włącza dopiero **START**.
> Bez uprawnień administratora sterownik WinDivert się nie załaduje.

## Język / Language

Tłumaczenia mieszkają w plikach **`lang/<kod>.json`** (w komplecie: `lang/pl.json` z pełnymi polskimi znakami oraz `lang/en.json`). Przy starcie aplikacja **skanuje katalog `lang/`** i sama wykrywa dostępne języki, a język startowy dobiera według ustawień systemu (system po polsku → polski; brak dopasowania → angielski). W prawym górnym rogu okna jest lista **Język / Language**, którą można przełączyć w dowolnej chwili - UI przebuduje się na wybrany język, zachowując bieżące ustawienia.

Tłumaczone jest **wszystko** w interfejsie: zakładki, etykiety, przyciski, podpowiedzi, nagłówki kolumn, statystyki, panel sesji, dziennik zdarzeń, komunikaty w logu, okna dialogowe, a także komunikaty błędów (wyjątki pokazywane użytkownikowi). W kodzie używa się wyłącznie **kluczy** (np. `app.tabs.statistics`), a tekst pochodzi z pliku języka; gdy w wybranym języku brakuje klucza, używany jest angielski, a w ostateczności sam klucz. (Tryb wiersza poleceń - CLI - jest **zawsze po angielsku**, niezależnie od języka systemu i UI.)

**Dodanie nowego języka** nie wymaga zmian w kodzie: skopiuj `lang/en.json` np. do `lang/de.json`, przetłumacz wartości i uzupełnij nagłówek `"_meta": {"code": "de", "name": "Deutsch"}` - język pojawi się na liście po ponownym uruchomieniu. Uszkodzony plik języka jest pomijany (nie wywali aplikacji).

The UI is bilingual (Polish and English). On startup the language follows your system locale (Polish system → Polish, otherwise English) and can be switched anytime via the selector in the top-right corner.

## Wymagania

- Windows 10/11 (64-bit), Python 3.10+ (z opcją tcl/tk)
- Uprawnienia administratora
- `pydivert` (przechwytywanie ruchu), `psutil` (celowanie w proces - opcjonalne)

## Okno programu

Okno **dopasowuje się do ekranu i do skalowania systemu (DPI)**. Rozmiar startowy jest liczony z rozdzielczości (mieści się na 1366×768 i rośnie na Full HD / 2K / 4K), a wszystkie wymiary - szerokości kolumn, wysokość wierszy tabel, marginesy wykresu, zawijanie tekstu - skalują się razem z czcionką. Program deklaruje się jako **Per-Monitor-V2 DPI aware**, więc przeniesienie okna na drugi monitor o innym skalowaniu nie rozmywa interfejsu.

Rozmiar i pozycja okna, wybrana zakładka, język, zwinięte sekcje, podział log/zakładki oraz sortowanie tabel są zapamiętywane w pliku `bean_network_tester_ui.json` (obok profili). Zapisana geometria jest przed użyciem sprawdzana - jeśli monitor zniknął, okno wraca na środek bieżącego ekranu.

- **Sterowanie** - wszystkie ustawienia zakłóceń, pogrupowane w **zwijane sekcje** (stan zwinięcia jest zapamiętywany). Na szerokim oknie sekcje układają się **w dwie kolumny** (zamiast jednej wąskiej i pustej prawej połowy), więc przewijania jest znacznie mniej. Cała zakładka jest przewijana - również **kółkiem myszy**.
- **Statystyki** - trzy podzakładki, żeby nic nie było ucinane na małych ekranach:
  - **Na żywo** - liczniki (pakiety, utracone, uszkodzone, zerwane…) i wykres przepustowości; siatka liczników sama dobiera liczbę kolumn do szerokości okna. Przycisk „Eksportuj CSV”.
  - **Sesja** - seed, czas trwania, zużyte dane, szczyty + przyciski „Oznacz błąd”, „Zapisz raport repro”, „Kopiuj komendę CLI”.
  - **Zdarzenia** - dziennik zdarzeń (START/STOP/ZMIANA/SCENARIUSZ/BŁĄD/RESET).
- **Połączenia** - podgląd, z jakimi adresami IP:port gada testowany system. Kolumny: **proces**, **protokół**, zdalne IP, porty, liczba pakietów, **KB**, **czas trwania** i **czas od ostatniej aktywności**. Do tego wyszukiwarka (z opóźnieniem, żeby nie mielić tabeli przy każdym znaku), sortowanie po kliknięciu w nagłówek, **„Zamroź”** (wiersze przestają uciekać spod kursora) oraz **menu pod prawym przyciskiem myszy**: kopiuj wiersz / adres IP, **„Celuj w ten proces”**, **„Ogranicz do tego IP:port”** - wypełnia pola filtrów jednym kliknięciem.
  Tabela jest **wirtualizowana**: rysuje tylko te wiersze, które faktycznie widać, więc przewijanie jest natychmiastowe niezależnie od tego, czy ma 400 wierszy, czy kilkaset tysięcy. Dawny sztywny limit 400 wierszy zniknął - ile pokazać, ustawiasz polem **„Limit wierszy”** (sekcja *Tabele*; 0 = bez limitu, domyślnie 50 000).
- Na dole: **START/STOP**, **Zastosuj zmiany** i **Wczytaj/Zapisz plik**, a pod nimi log. Ten pasek jest zakotwiczony przy dolnej krawędzi - żadna zakładka nie jest w stanie go zasłonić.

### Kiedy zmiany wchodzą w życie

**Nic nie aplikuje się samo.** Preset, profil, tryb LAN i wczytany plik konfiguracji **tylko wypełniają formularz**. Do działającej sesji przekazuje je dopiero **„Zastosuj zmiany”** - przycisk **podświetla się**, gdy formularz różni się od tego, co faktycznie robi silnik. Pasek pod tytułem mówi, co widzisz:

| Prefiks | Znaczenie |
|---|---|
| `Podgląd:` | aplikacja zatrzymana - to opis tego, co się stanie po STARCIE |
| `Aktywne:` | dokładnie to jest w tej chwili stosowane do ruchu |
| `Niezastosowane zmiany:` | formularz został zmieniony - kliknij „Zastosuj zmiany” |

W trakcie działającej sesji **zablokowane są dwa elementy** (odblokowują się po STOP):
**filtr ruchu** (stosowany tylko przy STARCIE) oraz **wybór języka** (zmiana języka przebudowuje całe UI). Przycisk STOP jest czerwony - nie da się go pomylić ze START.

Nieaktywne pola (np. „Okres”/„Procent przerwy”, gdy „Włącz” jest odznaczone) są **wyszarzone razem z etykietami** - od razu widać, co jest aktywne, a co nie.

### Skróty klawiaturowe

| Skrót | Działanie |
|---|---|
| `F5` | START / STOP |
| `Ctrl+Enter` | Zastosuj zmiany |
| `Ctrl+S` / `Ctrl+O` | Zapisz / Wczytaj plik konfiguracji |
| `Ctrl+L` | Wyczyść log |

### Walidacja pól

Pola liczbowe są sprawdzane **na żywo, razem z zakresem** (np. utrata 0-100%, latencja 0-600000 ms): błędne pole robi się czerwone, a powód pojawia się pod sekcją. To samo dotyczy wyrażeń filtrów. Ten sam zakres obowiązuje w CLI - `--loss 250` to teraz błąd, a nie ciche obcięcie do 100%.

## Opis wszystkich opcji

**Ruch do modyfikacji** - który ruch w ogóle przechwytywać. Do wyboru: w obie strony (TCP+UDP+ICMP), tylko wychodzący, tylko przychodzący, tylko TCP, tylko UDP, tylko ICMP (ping), tylko loopback (127.0.0.1/::1 - test komunikacji między procesami lokalnymi). Każdy filtr obejmuje **IPv4 i IPv6**. (Jeśli ping „nie reaguje”, prawie zawsze chodzi o to, że wybrany filtr nie obejmuje ICMP.)

> **Uwaga:** presety portowe („tylko DNS/HTTP/HTTPS”) nie istnieją - do zawężenia po portach służy pole **Port** w „Celuj w adres docelowy”, które rozumie listy, zakresy i wykluczenia (`80,443,8000-8100`, `!53`). Dwa miejsca decydujące o portach, z różną semantyką, tylko by myliły.

**Filtr ruchu** jest stosowany przy starcie, dlatego podczas działania jest **zablokowany** - aby go zmienić, zatrzymaj (STOP), wybierz inny i uruchom ponownie (START).

**Tryb LAN** - pole wyboru „Tryb LAN (tylko sieć lokalna, bez internetu)”. Odrzuca ruch do/od adresów publicznych (internet), a przepuszcza sieć lokalną: 10.0.0.0/8, 172.16-31.x, 192.168.x, loopback, link-local i CGNAT. Symuluje sytuację „LAN działa, internetu brak” - test zachowania aplikacji bez dostępu do internetu (np. brak bramy/WAN, portal przechwytujący).

**Celuj w proces** - zawęź działanie do wybranych aplikacji: nazwa procesu (np. `chrome.exe`),
PID, lista po przecinku, zakres PID, wildcard lub wyrażenie regularne - patrz
[Składnia filtrów](#składnia-filtrów-proces--ip--port). Reszta ruchu na komputerze pozostaje
nietknięta. Puste pole = cały ruch. Wymaga `psutil`.

**Limit prędkości** - maksymalna przepustowość osobno dla pobierania (ruch przychodzący)
i wysyłania (wychodzący), w KB/s. 0 = bez limitu. Ping to małe pakiety, więc limit prędkości
prawie go nie zmienia - do testu limitu użyj pobierania pliku. Wartość dodatnia zawsze coś
ogranicza: skrajnie mały limit (poniżej 1 B/s) jest podłogowany do 1 B/s, nie zamienia się
cicho w „bez limitu”.

**Bufor** - pojemność bufora łącza z limitem, w milisekundach (0 = bufor bez limitu).
Określa, ile opóźnienia kolejki może narosnąć na łączu z ustawionym limitem, zanim zacznie
porzucać nadmiar (bufferbloat). Bez tego bufora token bucket mógł „uciec” o dziesiątki sekund
w przyszłość: pakiety niosły ekstremalne opóźnienie, a podniesienie limitu w trakcie sesji
(np. krok harmonogramu „łącze wraca”) nie odnosiło skutku, bo zaległy bufor gasił każdy
kolejny szybszy krok. Przy buforze `N` ms opóźnienie jest ograniczone do ~`N` ms, nadmiar
leci jako „Odrzuc. przez limit” (osobny licznik, nie „Utracone” ani „Bufor przepełn.”),
a po podniesieniu limitu przepustowość wraca w ~`N` ms. Domyślnie 1000 ms. Działa tylko przy
ustawionym limicie pobierania/wysyłania lub harmonogramie.

**Opóźnienie (ping)** - *Latencja*: ile ms doliczyć do każdego pakietu (podnosi ping).
*Jitter*: losowe wahanie opóźnienia (±ms), przez co ping skacze i miesza się kolejność pakietów.
Dwie rzeczy warto wiedzieć: (1) jitter dokłada każdemu pakietowi niezależne, losowe opóźnienie,
więc pakiety mogą się w kolejce wyprzedzać - jitter z natury **zmienia kolejność pakietów**
(prawdziwa sieć robi tak samo). (2) Ujemne wychylenie jest przycinane do zera, więc gdy jitter
jest **większy od latencji**, średnie doliczone opóźnienie rośnie powyżej samej latencji
(np. latencja 0, jitter 50 ms daje ~połowę pakietów bez opóźnienia i średnią ~12 ms, nie 0).
Przy latencji większej niż jitter efekt jest pomijalny.

**Zakłócenia (%)** - *Utrata*: procent pakietów znikających bez śladu (5% to już wyraźnie
zrywająca się sieć). *Uszkodzenie*: procent pakietów z przekłamanym bitem danych - dotyczy
tylko pakietów z ładunkiem (payloadem); pakiety bez danych (np. czyste ACK, SYN) nie mają czego
przekłamać, więc przechodzą nietknięte i **nie są liczone jako uszkodzone**.
*Duplikacja*: procent pakietów wysyłanych podwójnie.

**Przerwy w łączu (flapping)** - cykliczne całkowite zrywanie ruchu: co *Okres* sekund łącze
jest martwe przez podany procent czasu. Symuluje migające połączenie.

**Zaawansowane (NAT / połączenia):**
- *Celuj w cel (IP/port)* - psuj tylko ruch do/od wybranych serwerów. Oba pola przyjmują listy, zakresy, CIDR, wildcardy, porównania, wykluczenia i wyrażenia regularne - patrz [Składnia filtrów](#składnia-filtrów-proces--ip--port). Np. IP `10.0.0.1-10.0.0.50,!10.0.0.7`, port `80,443,8000-8100`. Puste = dowolne.
- *Gubione TCP SYN (%)* - procent gubionych pakietów rozpoczynających połączenie; symuluje sytuację, gdy połączenie nie chce się nawiązać (test ponawiania prób) - przydatne przy testach zza NAT.
- *Maks. rozmiar (MTU)* - gub pakiety większe niż N bajtów; odwzorowuje „czarną dziurę MTU” z tuneli/VPN/za NAT (małe przechodzą, duże znikają). 0 = wyłączone.
- *Skok latencji* - z podanym prawdopodobieństwem doklej dodatkowe opóźnienie (ms) do pojedynczego pakietu; odwzorowuje chwilowe „lagi”.
- *NAT timeout* - jeśli połączenie milczy dłużej niż N sekund, kolejny pakiet przychodzący jest odrzucany (mapowanie „znika”); test keep-alive. 0 = wyłączone.
- *Zrywanie TCP (RST)* - procent połączeń nagle zrywanych pakietem RST; wymusza reconnect. **Dotyczy wyłącznie TCP** (RST to pojęcie TCP-owe; UDP nie da się „zerwać” - użyj strat albo przerwy w łączu). Przycisk **Zerwij TCP teraz** zrywa wszystkie aktywne połączenia TCP na ~3 s.
- *Harmonogram* - zmienna przepustowość w czasie: `czas:pobieranie:wysyłanie` w KB/s, po przecinku. Np. `2:100:0, 2:500:0` = 2 s po 100 KB/s, potem 2 s po 500, w pętli. Gdy harmonogram jest niepusty, **zastępuje** stałe pola „Pobieranie/Wysyłanie” - GUI wyszarza je i mówi o tym wprost.

**Sesja:**
- *Czas trwania (s)* - po tylu sekundach program **sam się zatrzyma** (dokładnie tak, jakbyś kliknął
  STOP): zakłócenia znikają, sterownik zostaje zwolniony. `0` = działa aż do STOP-a (zachowanie jak
  dotychczas - domyślne). Odpowiednik `--duration` w CLI; jak filtr ruchu, brany jest pod uwagę
  **tylko przy STARCIE** („Zastosuj zmiany” go nie rusza). Wartość zapisuje się w pliku konfiguracji
  i w komendzie reprodukcji.

**Powtarzalność i scenariusz:**
- *Seed* - ustaw dowolną liczbę, aby każdy przebieg losował tak samo (błąd da się odtworzyć). Puste = za każdym razem inaczej.
- *Scenariusz* - plik JSON zmieniający ustawienia w czasie rzeczywistym (np. po 10 s dodaj ping, po 20 s zerwij). „Pętla” odtwarza go w kółko. Przykłady w katalogu `scenarios/` (kawiarniane Wi-Fi, komórka LTE→3G, przeciążony VPN, padający DNS, przeciążony serwer gry, zerwanie w środku uploadu, zablokowany backend/API).

**Profile** - gotowe presety **posortowane od najlepszego (góra) do najgorszego (dół)**: Idealna sieć, Dobre WiFi, Sieć 5G, Sieć LTE/4G, DSL domowy, Słabe WiFi, Kawiarnia (zatłoczone WiFi), Sieć 3G, Roaming zagraniczny, Łącze satelitarne, Modem 56k, Fatalna sieć - oraz Twoje własne (zapis pod nazwą). Program **startuje zawsze na „Idealnej sieci”** (nic nie jest psute, dopóki sam czegoś nie ustawisz). Presetów wbudowanych nie da się usunąć - przycisk „Usuń” jest wtedy nieaktywny.

W CLI (`--preset`) preset można podać przez **kanoniczne id** albo **nazwę w dowolnym języku UI** (bez rozróżniania wielkości liter i polskich znaków - `"Idealna siec"` też zadziała). Id: `presets.perfect`, `presets.good_wifi`, `presets.5g`, `presets.lte`, `presets.dsl`, `presets.weak_wifi`, `presets.cafe`, `presets.3g`, `presets.roaming`, `presets.satellite`, `presets.modem56k`, `presets.terrible`.

## Składnia filtrów (proces / IP / port)

Trzy pola - **Celuj w proces**, **IP** i **port** (w „Celuj w cel”) - mówią tym samym mini-językiem.
Ta sama składnia będzie używana w każdym kolejnym polu filtrującym, które pojawi się w narzędziu.
Działa identycznie w GUI i w CLI (`--target`, `--dst-ip`, `--dst-port`).

### Elementy składni

| Zapis | Znaczenie | Przykład |
|---|---|---|
| `a,b,c` | **lista** - pasuje którakolwiek z wartości | `80,443` |
| `a-b` | **zakres**, oba końce **włącznie** | `8000-8100`, `10.0.0.1-10.0.0.50` |
| `>` `<` `>=` `<=` | **porównanie** (liczbowo; dla IP po wartości adresu) | `>1024`, `<=80`, `>10.0.0.5` |
| `!` | **wykluczenie** - „różne od” | `!53` |
| `*` `?` | **wildcard** (`*` = dowolny ciąg, `?` = jeden znak) | `chrome*`, `192.168.1.*` |
| `re:` | **wyrażenie regularne** (Python `re`, bez rozróżniania wielkości liter) | `re:^chrome\.exe$` |
| `x.x.x.x/n` | **CIDR** (tylko pole IP) | `192.168.1.0/24`, `2001:db8::/32` |

Puste pole = **wszystko** (brak filtrowania). Spacje wokół przecinków i członów są ignorowane.

### Jak łączą się człony (to najważniejsze)

```
pasuje = (brak członów pozytywnych LUB pasuje którykolwiek pozytywny) ORAZ nie pasuje żaden z "!"
```

Innymi słowy: **pozytywy sumują się (OR), a wykluczenia odejmują (AND NOT)**.
Kolejność członów nie ma znaczenia - `80,!53` znaczy dokładnie to samo co `!53,80`.

| Wpis | Znaczy |
|---|---|
| *(puste)* | wszystko |
| `443` | tylko port 443 |
| `80,443` | tylko 80 **lub** 443 |
| `!53` | **wszystko oprócz** 53 (bo nie ma żadnego członu pozytywnego) |
| `!53,!443` | wszystko oprócz 53 i 443 |
| `1000-2000,!1500` | 1000-2000, ale bez 1500 |
| `>1024,!3389` | wszystko powyżej 1024, ale nie 3389 |
| `80,443,8000-8100,>9000,!8080` | 80, 443, 8000-8100 i wszystko powyżej 9000 - bez 8080 |

### Pole „Celuj w proces”

Człon może być **nazwą** albo **PID-em** - można je mieszać w jednym polu.

* **Nazwa** (bez `*` i bez `re:`) działa jak **podciąg, bez rozróżniania wielkości liter**:
  `chrome` łapie `chrome.exe` **oraz** `chromedriver.exe`. (Tak działało to od zawsze - zachowane
  celowo, żeby stare konfiguracje i profile nadal działały.)
* **PID** - sam numer (`12345`), zakres (`1000-2000`) lub porównanie (`>1000`).
* **Wildcard** i **`re:`** dopasowują się do **nazwy** procesu.
* Porównania `>` `<` `>=` `<=` mają sens tylko dla **PID-a** (liczby). `>chrome` to **błąd** -
  narzędzie powie o tym wprost, zamiast po cichu nic nie dopasować.

```
chrome.exe                     wszystkie procesy z "chrome.exe" w nazwie
chrome, !chromedriver          chrome, ale NIE chromedriver
chrome.exe, firefox.exe        dwie aplikacje naraz
12345                          konkretny PID
12345, 6789                    dwa PID-y
1000-2000                      wszystkie procesy o PID z tego zakresu
>1000                          wszystkie procesy o PID > 1000
firefox*                       nazwa zaczynająca się od "firefox"
re:^(chrome|firefox)\.exe$      dokładnie chrome.exe albo firefox.exe
firefox, 12345                 nazwa i PID w jednym polu
```

Wszystkie pasujące procesy oddają swoje porty lokalne - celowanie obejmuje **sumę** ich portów.
Lista jest odświeżana w trakcie sesji (co ~2 s), więc nowo otwarte połączenia procesu są łapane.

### Pole „IP”

Obsługiwane jest **IPv4 i IPv6**. Reguła nigdy nie dopasowuje adresu z innej rodziny -
reguła IPv4 nie złapie adresu IPv6 i odwrotnie (można je spokojnie mieszać w jednym polu).

```
1.2.3.4                        jeden adres
1.2.3.4, 8.8.8.8               dwa adresy
10.0.0.1-10.0.0.50             zakres (oba końce włącznie)
10.0.0.1-10.0.0.50, !10.0.0.7  zakres z dziurą
192.168.1.0/24                 cała podsieć (CIDR)
192.168.1.*                    to samo wildcardem
!8.8.8.8                       wszystko oprócz 8.8.8.8
>10.0.0.5                      adresy "większe" niż 10.0.0.5
2001:db8::/32                  podsieć IPv6
2001:db8::1-2001:db8::ff       zakres IPv6
10.0.0.0/8, 2001:db8::/32      IPv4 i IPv6 w jednym polu
re:^10\.                        wszystko z 10. na początku
```

Zapis adresu nie ma znaczenia: `2001:0db8:0000:0000:0000:0000:0000:0001` i `2001:db8::1`
to dla narzędzia ten sam adres.

### Pole „port”

```
443                            jeden port
80,443                         lista
8000-8100                      zakres (oba końce włącznie)
>1024                          porty wysokie
<=1024                         porty uprzywilejowane
!53                            wszystko oprócz DNS
80,443,8000-8100,!8080         mieszanka
```

Dozwolony zakres to **0-65535**; `99999` to błąd, a nie ciche pominięcie.

### Wyrażenia regularne (`re:`)

Prefiks `re:` jest **obowiązkowy** - bez niego człon jest zwykłą wartością. Dzięki temu
`chrome.exe` to nazwa pliku (kropka jest kropką), a nie wzorzec regex.

| Wzorzec | Łapie |
|---|---|
| `re:^chrome` | nazwy zaczynające się od `chrome` |
| `re:^chrome\.exe$` | **dokładnie** `chrome.exe` (bez `chromedriver.exe`) |
| `re:^(chrome\|firefox)\.exe$` | dokładnie `chrome.exe` albo `firefox.exe` |
| `re:(node\|python)` | nazwy zawierające `node` lub `python` |
| `re:^\d+$` | (w polu port/PID) sama liczba |
| `re:^10\.` | (w polu IP) adresy z `10.` na początku |
| `!re:^chrome` | **wszystko oprócz** nazw zaczynających się od `chrome` |

Wzorce działają **bez rozróżniania wielkości liter** i szukają dopasowania w dowolnym miejscu
(`re.search`) - jeśli chcesz dopasowania od początku do końca, użyj `^` i `$`.

**Przecinek wewnątrz regexa trzeba poprzedzić ukośnikiem** (`\,`), bo przecinek rozdziela człony:

```
re:^ch.{1\,8}e\.exe$          poprawnie - {1,8} z ukośnikiem przed przecinkiem
re:^ch.{1,8}e\.exe$           BŁĄD - zostanie rozcięte na "re:^ch.{1" i "8}e\.exe$"
```

### Przypadki, które bywają mylące

* **`chrome` łapie też `chromedriver`, ale `chrome.exe` już nie.** Goła nazwa to *podciąg*:
  tekst „chrome" występuje w `chromedriver.exe`, ale tekst „chrome.exe" już nie (bo tam jest
  `chrome` + `driver.exe`). Czyli `chrome.exe` → tylko `chrome.exe`; `chrome` → `chrome.exe`
  **i** `chromedriver.exe`.
* **`chrome*` jest szersze, niż wygląda.** Gwiazdka to „dowolny ciąg", więc `chrome*` łapie
  `chromedriver.exe` dokładnie tak samo jak `chrome`. Chcesz dokładnie jedną aplikację?
  Użyj `re:^chrome\.exe$` albo dopisz wykluczenie: `chrome, !chromedriver`.
* **`8*` w polu port to wildcard na tekście liczby**, więc łapie `8`, `80`, `8080` i `8443` -
  ale **nie** `443`. Prawie zawsze chodziło o zakres: `8000-8999`. Wildcardów w portach używaj świadomie.
* **`80,443,!8080` to po prostu `80,443`.** Wykluczenie, które i tak nic nie odcina, nie jest błędem
  - jest po prostu bezużyteczne.
* **`!53` obejmuje też ruch bez portu** (np. ICMP/ping). „Wszystko oprócz 53” dosłownie znaczy
  „wszystko, co nie jest portem 53”, a pakiet ICMP nie jest portem 53. Jeśli chcesz tylko TCP/UDP,
  zawęź **Filtr ruchu**.
* **Pusty człon jest błędem**, nie „wszystkim”: `80,,443` i `80,!` zostaną odrzucone. Puste **całe pole**
  oznacza „wszystko”.
* **IP i port łączy AND.** `IP=10.0.0.0/8` + `port=443` to „ruch do sieci 10.x **i jednocześnie** na port 443”.
  Chcesz „albo/albo”? Zostaw drugie pole puste i zrób dwa przebiegi.
* **`>chrome` to błąd.** Porównania działają na liczbach (PID), nie na nazwach.
* **`2000-1000` to błąd** (odwrócony zakres), a nie pusty zbiór.
* **Wildcard nie jest regexem.** W `chrome*` gwiazdka znaczy „dowolny ciąg”; w `re:chrome*`
  znaczy „litera `e` powtórzona 0+ razy”. Jeśli piszesz `re:`, piszesz regexa.

Każdy błąd składni jest zgłaszany **od razu**: w GUI pole robi się czerwone i pod spodem pojawia się
powód (w języku interfejsu), a CLI kończy się czytelnym `error: ...` - nigdy cichym „nic nie działa”.

## Statystyki (co znaczą liczniki)

Wykres przepustowości ma teraz oś Y z wartościami (KB/s), siatkę, „ładnie” zaokrągloną skalę oraz bieżące odczyty down/up w rogu. Pobieranie/Wysyłanie (KB/s na żywo), Pakiety (ile przeszło), W kolejce (czekające - rośnie przy
opóźnieniu/limicie), Utracone, Uszkodzone, Zduplikowane, Bufor przepełn. (porzucone przy
przeciążeniu narzędzia), Porzuc. przy stopie (czekały w kolejce, gdy nacisnięto STOP), Odrzuc. przez limit (porzucone przez pełny bufor limitu prędkości -
liczone osobno od strat i od „Bufor przepełn.”), SYN odrzucone, MTU odrzucone, NAT wygasło,
RST zerwane, LAN: internet odcięty, RST wysłane.

### Reprodukcja błędu (panel „Sesja i reprodukcja”)

Zaprojektowane tak, by po wystąpieniu błędu odtworzyć dokładnie te same warunki:

- **Seed (efektywny)** - nawet gdy zostawisz pole Seed puste, program wylosuje i zapamięta konkretny seed. Wpisz go później w pole Seed i uruchom ponownie, aby dostać te same losowania.
- **Powtarzalny flapping** - wzorzec przerw łącza liczony jest względem startu sesji, więc przy tych samych ustawieniach powtarza się identycznie między uruchomieniami (a nie zależy od zegara systemowego).
- **Co dokładnie odtwarza seed** - seed odtwarza **decyzje** silnika (które pakiety zostaną porzucone, uszkodzone, zduplikowane, o ile opóźnione), a nie **liczbę pakietów**. Ruch, który przechodzi przez łącze, zależy od tego, co w danej chwili robią aplikacje i system, więc dwa przebiegi z tym samym seedem dadzą te same *proporcje* (np. 15,8% strat w obu), ale nie identyczne liczniki co do sztuki. Do porównań w CI używaj wskaźników (%), nie surowych liczb pakietów.
- **Start / Czas trwania / Efektywna utrata / Szczyt kolejki / Szczyt down-up** - szybki obraz przebiegu.
- **Zużycie danych** - Pobrano / Wysłano / Razem (MB) narastająco od startu oraz średnia przepustowość sesji; od razu wiesz, ile danych aplikacja zużyła. (W raporcie jest też „próbowano MB” - ile aplikacja chciała przesłać przed odjęciem strat/limitów.)
- **Dziennik zdarzeń** ze znacznikami czasu: start, zmiany ustawień, kroki scenariusza, zerwania, oraz Twoje znaczniki błędu - z **sortowaniem** po kliknięciu w nagłówek kolumny.
- **Zaznacz moment błędu** - kliknij dokładnie gdy zobaczysz błąd; wstawia znacznik z czasem do dziennika.
- **Zapisz raport reprodukcji** - jeden plik JSON z kompletem: seed, wszystkie ustawienia, liczniki, metryki, dziennik zdarzeń, połączenia oraz **gotową komendę CLI**, która odtwarza warunki.
- **Kopiuj komendę CLI** - od razu do schowka: `BeanNetworkTester.exe --seed … --loss … --duration …`
  (komenda dopasowuje się do builda: z repozytorium dostaniesz `python bean_network_tester.py …`).

## Plik konfiguracji (wspólny GUI + CLI)

Przyciski „Zapisz/Wczytaj plik” zapisują wszystkie ustawienia do JSON. Ten sam plik działa
w CLI przez `--config`. Kolejność pierwszeństwa: domyślne < plik < preset < flagi.

## Tryb wiersza poleceń (CLI)

CLI działa **z tego samego pliku `BeanNetworkTester.exe`**, co GUI: uruchomienie z jakimkolwiek
argumentem startuje tryb tekstowy (bez okna, bez tkintera), a bez argumentów - GUI.
Komunikaty i `--help` są zawsze po angielsku.

```bat
:: GUI
BeanNetworkTester.exe

:: CLI (z tego samego exe)
BeanNetworkTester.exe --loss 5 --latency 100 --down 1024 --target chrome.exe
BeanNetworkTester.exe --preset "Sieci 3G" --duration 60
```

> Pracujesz z repozytorium (bez builda)? Wszędzie zamiast `BeanNetworkTester.exe` wpisz
> `python bean_network_tester.py` - wszystkie flagi i kody wyjścia są identyczne.

### Kody wyjścia (kontrakt dla CI/CD)

Każdy sposób zakończenia ma własny kod - pipeline nie musi parsować tekstu:

| Kod | Nazwa | Kiedy |
|---|---|---|
| `0` | ok | sesja przebiegła i wszystkie sprawdzenia przeszły |
| `1` | runtime | nie dało się wystartować (brak `pydivert`, sterownik, awaria silnika) |
| `2` | usage | zła linia poleceń (nieznana flaga, zły typ) - kod argparse |
| `3` | config | błędne ustawienia: wyrażenie, harmonogram, zakres, preset, plik konfiguracji |
| `4` | scenario | plik scenariusza nie istnieje albo jest błędny |
| `5` | io | nie dało się zapisać artefaktu (raport repro, plik konfiguracji) |
| `6` | assertion | przebieg się udał, ale `--min-packets` / `--fail-on-no-traffic` nie przeszło |
| `7` | permission | potrzebne uprawnienia administratora, których nie ma |
| `130` | interrupted | Ctrl+C (SIGINT) |
| `143` | terminated | SIGTERM (anulowanie joba, `docker stop`) |

Te same kody wypisuje `BeanNetworkTester.exe --help`.

### Wyjście: log na stderr, dane na stdout

- **stderr** - log dla człowieka, z prefiksem `[bean]` (start, seed, błędy, powód zatrzymania),
- **stdout** - dane: linie raportów, a przy `--format json` **NDJSON** (jeden obiekt JSON na linię:
  kolejne `sample`, na końcu `summary` z kodem wyjścia, seedem i komendą repro).

```bat
BeanNetworkTester.exe --simulate --duration 30 --format json > run.ndjson
```

### Wszystkie parametry CLI

**Zakłócenia łącza**

| Flaga | Jednostka | Opis |
|---|---|---|
| `--loss` | % | procent gubionych pakietów |
| `--corrupt` | % | procent pakietów z przekłamanym bitem |
| `--dup` | % | procent pakietów wysłanych podwójnie |
| `--latency` | ms | stałe opóźnienie doklejane do każdego pakietu |
| `--jitter` | ms | losowe wahanie opóźnienia (±) |
| `--down` `--up` | KB/s | limit przepustowości (0 = bez limitu) |
| `--buffer` | ms | bufor łącza dla limitu prędkości (0 = bez limitu); ogranicza opóźnienie kolejki, nadmiar leci jako „Odrzuc. przez limit” |
| `--spike-prob` `--spike-ms` | % / ms | z podanym prawdopodobieństwem doklej dodatkowe opóźnienie |
| `--syn-drop` | % | procent gubionych pakietów TCP SYN |
| `--max-size` | B | „czarna dziura MTU” - gub pakiety większe niż N bajtów (0 = wył.) |
| `--nat-timeout` | s | po N s ciszy mapowanie NAT „znika” (0 = wył.) |
| `--rst-prob` `--rst-cooldown` | % / s | procent połączeń zrywanych RST-em i czas trzymania zerwanego |
| `--flap-period` `--flap-down` | s / % | cykliczne zrywanie łącza: co ile i na jaki ułamek okresu |
| `--rate-schedule` | - | zmienna przepustowość: `"czas:pobieranie:wysyłanie,..."` w KB/s, w pętli |
| `--lan-mode` | - | tryb LAN: odetnij internet (adresy publiczne), zostaw sieć lokalną |

**Celowanie** (wszystkie trzy przyjmują pełną [składnię filtrów](#składnia-filtrów-proces--ip--port): listy, zakresy, `!`, `>`, `<`, `>=`, `<=`, wildcardy, `re:`, a `--dst-ip` dodatkowo CIDR)

| Flaga | Opis | Przykłady |
|---|---|---|
| `--target` | procesy: nazwa, PID, zakres PID, wildcard, regex | `--target chrome.exe`<br>`--target "chrome,!chromedriver"`<br>`--target ">1000"` |
| `--dst-ip` | zdalne adresy IP (IPv4 i IPv6) | `--dst-ip 1.2.3.4`<br>`--dst-ip "10.0.0.1-10.0.0.50,!10.0.0.7"`<br>`--dst-ip "192.168.1.0/24"`<br>`--dst-ip "2001:db8::/32"` |
| `--dst-port` | zdalne porty (0-65535) | `--dst-port 443`<br>`--dst-port "80,443,8000-8100"`<br>`--dst-port "!53"`<br>`--dst-port ">1024"` |
| `--filter` | który ruch w ogóle przechwytywać (IPv4 + IPv6): `both,out,in,tcp,udp,ping,loopback` | `--filter tcp` |

**Blokowanie (firewall)** - twarde odcięcie (drop) ruchu do wskazanych celów. Blokada działa na **IP LUB port** (puste pole jest pomijane, więc sam `--block-port 443` blokuje 443 do każdego adresu). Ta sama [składnia filtrów](#składnia-filtrów-proces--ip--port) co wyżej; respektuje celowanie w proces (blokuje tylko ruch celu).

| Flaga | Opis | Przykłady |
|---|---|---|
| `--block-ip` | zablokuj zdalne adresy IP (IPv4 i IPv6) | `--block-ip 1.2.3.4`<br>`--block-ip "10.0.0.0/8,!10.0.0.1"` |
| `--block-port` | zablokuj zdalne porty (0-65535) | `--block-port 443`<br>`--block-port "80,443,8000-8100"` |

> W `cmd.exe`/PowerShell **weź wyrażenie w cudzysłów**, jeśli zawiera przecinek, `!`, `>`, `<` lub `*`
> - inaczej powłoka zinterpretuje je po swojemu. Komenda odtwarzająca sesję (`Kopiuj komendę CLI`
> i linia `Reproduce:`) cytuje je za Ciebie.

**Uruchomienie i raportowanie**

| Flaga | Opis |
|---|---|
| `--preset NAZWA` | preset po kanonicznym id lub nazwie w dowolnym języku UI |
| `--config PLIK` / `--save-config PLIK` | wczytaj / zapisz ustawienia (JSON, wspólne z GUI) |
| `--scenario PLIK` `--loop` | scenariusz na osi czasu (JSON) i jego zapętlenie |
| `--seed N` | ziarno losowości - ten sam przebieg da się powtórzyć |
| `--duration N` | **czas pracy w sekundach** (0 = do Ctrl+C). To samo pole jest w GUI (sekcja „Sesja”) |
| `--row-limit N` | ustawienie **tylko dla GUI**: maks. wierszy w tabelach (0 = bez limitu; domyślnie 50 000). W samym CLI (bez okna) nic nie robi - jest jedynie zapisywane do pliku konfiguracji i działa dopiero, gdy ten config otworzysz w GUI. Odpowiednik pola „Limit wierszy” |
| `--interval N` | co ile sekund raportować (musi być > 0) |
| `--log-conns` | wypisz na końcu zaobserwowane połączenia |
| `--repro-out PLIK` | zapisz raport reprodukcji (JSON) |
| `--simulate` | sztuczny ruch zamiast WinDivert (test bez Windows, bez sterownika i bez admina) |
| `--gui` | wymuś GUI |
| `--version` | wersja i koniec |

**Wyjście i diagnostyka**

| Flaga | Opis |
|---|---|
| `-v`, `--verbose` | loguj, co program robi: efektywne ustawienia, skompilowane filtry, rozwiązane porty procesu, kroki scenariusza, otwarcie/zamknięcie sterownika |
| `-q`, `--quiet` | tylko błędy: żadnego logu ani raportów okresowych |
| `--log-level {error,warn,info,debug}` | jawny poziom logu (przebija `-v`/`-q`) |
| `--log-file PLIK` | dopisuj log (i raporty) także do pliku - gotowy artefakt CI |
| `--format {text,json}` | format stdout: tekst dla człowieka albo NDJSON dla pipeline’u |

**Pod CI/CD**

| Flaga | Opis |
|---|---|
| `--dry-run` | sprawdź konfigurację i wyjdź (nie dotyka sterownika, nie puszcza ruchu) - idealne do walidacji plików konfiguracji w pipeline |
| `--print-config` | wypisz efektywne ustawienia (po `domyślne < plik < preset < flagi`) jako JSON i wyjdź |
| `--min-packets N` | zakończ kodem `6`, jeśli złapano mniej niż N pakietów |
| `--fail-on-no-traffic` | skrót na `--min-packets 1` - **łapie filtr, który nie złapał niczego** |
| `--doctor` | sprawdź środowisko (admin, `pydivert`, stan sterownika WinDivert, resztki w `%TEMP%`) i wyjdź |
| `--cleanup-driver` | wyładuj zawieszony sterownik WinDivert (uwalnia zablokowany plik `.sys` **bez restartu systemu**) i wyjdź |

Kolejność pierwszeństwa: **domyślne < `--config` < `--preset` < flagi**.
Pełna lista: `BeanNetworkTester.exe --help`.

### Przykłady z celowaniem

```bat
:: tylko przeglądarka, ale bez jej sterownika testowego
BeanNetworkTester.exe --loss 10 --target "chrome,!chromedriver"

:: tylko ruch HTTPS do serwera testowego i do jego zapasowego adresu
BeanNetworkTester.exe --latency 300 --dst-ip "10.0.0.5,10.0.0.9" --dst-port 443

:: cała podsieć testowa, z wyjątkiem jednego hosta, na portach aplikacyjnych
BeanNetworkTester.exe --down 128 --dst-ip "10.0.0.0/24,!10.0.0.1" --dst-port "8000-8100"

:: wszystko OPRÓCZ DNS (żeby rozwiązywanie nazw działało, a reszta się psuła)
BeanNetworkTester.exe --loss 20 --dst-port "!53"

:: procesy o wysokim PID, ruch do IPv6
BeanNetworkTester.exe --jitter 80 --target ">1000" --dst-ip "2001:db8::/32"
```

### Przykłady z blokowaniem (firewall)

```bat
:: odetnij aplikacji dostęp do zewnętrznego API (serwer "padł")
BeanNetworkTester.exe --block-ip 203.0.113.10

:: zablokuj cały HTTPS - sprawdź, jak apka reaguje na brak połączenia
BeanNetworkTester.exe --block-port 443

:: zablokuj kilka portów LUB całą podsieć backendu (blokada łączy IP OR port)
BeanNetworkTester.exe --block-port "8080,9090" --block-ip 203.0.113.0/24

:: psuj tylko ruch swojej apki, a jej ruch do serwera płatności odetnij zupełnie
BeanNetworkTester.exe --latency 200 --target myapp.exe --block-ip 198.51.100.7
```

### Tryb `--simulate` (test bez Windows i bez admina)

Podgląd działania na sztucznym ruchu - nie wymaga WinDivert ani uprawnień:

```bat
BeanNetworkTester.exe --simulate --down 500 --loss 10 --duration 4 --interval 1
```

### Powtarzalność i scenariusze z CLI

```bat
BeanNetworkTester.exe --simulate --seed 42 --loss 20 --duration 10
BeanNetworkTester.exe --simulate --scenario scenarios/cafe-wifi.json
```

Seed gwarantuje identyczne **decyzje na pakiet** dla tej samej sekwencji pakietów.
Kroki scenariusza są kumulatywne (każdy nakłada łatkę na stan), a `action: reset_tcp`
zrywa w danym momencie połączenia TCP (stara nazwa `reset_now` nadal działa). Plik scenariusza
jest **walidowany** - losowy JSON kończy się czytelnym błędem, a nie „scenariuszem z 0 kroków”.

Każdy przebieg CLI kończy się wypisaniem **efektywnego seeda** i gotowej komendy do odtworzenia,
a `--repro-out plik.json` zapisuje pełny raport reprodukcji.

## Przepisy pod CI/CD

### 1. Degradacja łącza w tle testów E2E (GitHub Actions, Windows)

Testy jadą przy 300 ms opóźnienia i 5 % strat; shaper sam się wyłącza po 120 s,
więc żaden „zawieszony” krok nie zostawi zepsutej sieci na agencie.

```yaml
- name: Start the network shaper (background, self-stopping)
  shell: pwsh
  run: |
    $p = Start-Process -FilePath dist\BeanNetworkTester\BeanNetworkTester.exe `
      -ArgumentList '--latency','300','--loss','5','--duration','120',
                    '--dst-port','443','--fail-on-no-traffic',
                    '--format','json','--log-file','shaper.log' `
      -RedirectStandardOutput shaper.ndjson -PassThru
    "SHAPER_PID=$($p.Id)" >> $env:GITHUB_ENV

- name: Run the E2E suite under bad network
  run: npm run test:e2e

- name: Stop the shaper and check it actually impaired something
  if: always()
  shell: pwsh
  run: |
    Stop-Process -Id $env:SHAPER_PID -ErrorAction SilentlyContinue
    Get-Content shaper.ndjson | Select-Object -Last 1
```

> **Uwaga:** proces w tle uruchamiaj z `--duration` - to jest bezpiecznik. Nawet jeśli krok
> „Stop” nigdy nie wykona się (anulowanie joba, timeout), sesja zamknie się sama, sterownik
> zostanie zwolniony i agent odzyska normalną sieć.

### 2. Walidacja konfiguracji w pre-commit / PR (bez sterownika i bez admina)

```bat
BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```
Kod `0` = plik jest poprawny; `3` = jest błąd (z czytelnym komunikatem na stderr).

### 3. Krótki, powtarzalny przebieg z artefaktem

```bat
BeanNetworkTester.exe --preset presets.3g --seed 42 --duration 60 ^
  --repro-out repro.json --format json --fail-on-no-traffic > run.ndjson
```
Artefakty (`run.ndjson`, `repro.json`) wystarczą, żeby odtworzyć warunki 1:1 -
`repro.json` zawiera gotową komendę `cli_command`.

### 4. Sprzątanie środowiska agenta

```bat
BeanNetworkTester.exe --doctor
BeanNetworkTester.exe --cleanup-driver
```

## Zbudowanie pliku .exe

Na Windowsie:

```bat
pip install pyinstaller pydivert psutil
pyinstaller --noconfirm BeanNetworkTester.spec
```

Wynik: **`dist\BeanNetworkTester\BeanNetworkTester.exe`** (katalog z exe, sterownikiem
WinDivert, tłumaczeniami i ikoną). Ten jeden plik obsługuje **GUI i CLI**.

Trzy świadome decyzje builda (nie zmieniaj ich bez potrzeby - każda naprawia realny błąd):

- **podsystem konsolowy** (a nie `--noconsole`): inaczej exe nie ma `stdout`/`stderr`, a `cmd.exe`
  i PowerShell **nie czekają** na proces GUI - CI nie zobaczyłby ani wyjścia, ani kodu wyjścia.
  Przy starcie GUI program sam odłącza się od konsoli, więc po dwukliku nie zostaje czarne okno;
- **onedir** (a nie `--onefile`): `pydivert` niesie `WinDivert64.sys`, a onefile rozpakowywał go do
  `%TEMP%\_MEIxxxx`. Jądro trzyma otwarty uchwyt do wczytanego `.sys`, więc katalogu **nie dało się
  skasować** aż do restartu. W wersji katalogowej sterownik leży obok exe, na stałej ścieżce;
- **`asInvoker`** (a nie `--uac-admin`): `requireAdministrator` zawsze tworzy **nowy** proces przy
  elewacji - gubi potoki i kod wyjścia wołającego. Teraz GUI samo prosi o podniesienie uprawnień,
  a CLI kończy się kodem `7` z jasnym komunikatem, gdy uprawnień brakuje (`--simulate` ich nie wymaga).

Ikonę można wygenerować ponownie skryptem z użyciem Pillow (`pip install pillow`), ale do zwykłego działania Pillow nie jest potrzebne.

## Co może zaskoczyć (przeczytaj, zanim zgłosisz błąd)

- **`--duration` to bezpiecznik, nie tylko wygoda.** Bez niego sesja trwa do `Ctrl+C` / STOP.
  W CI **zawsze** podawaj `--duration`.
- **Zero ruchu = zielony przebieg.** Jeśli filtr nie złapie ani jednego pakietu, program działa
  poprawnie i kończy się kodem `0`. Chcesz, żeby to był błąd → `--fail-on-no-traffic`.
- **Filtr ruchu i czas trwania działają tylko od STARTU** (jak w GUI): „Zastosuj zmiany” ich nie rusza.
- **Po STOP pakiety czekające w kolejce opóźnienia są porzucane.** Przy `--latency 5000` to może być
  całkiem sporo pakietów naraz - to nie jest wyciek, to koniec sesji.
- **Limit prędkości ma bufor (`--buffer`, domyślnie 1000 ms).** Przy ofercie powyżej limitu nadmiar
  po zapełnieniu bufora leci jako „Odrzuc. przez limit” (osobny licznik) - to zachowanie zatkanego
  łącza, nie błąd. Podniesienie limitu w trakcie sesji zaczyna działać dopiero po opróżnieniu bufora
  (do ~`--buffer` ms). Chcesz stary, nieograniczony bufor (pakiety zamiast dropów, kosztem rosnącego
  opóźnienia)? Ustaw `--buffer 0`.
- **`--dst-port "!53"` łapie też ruch bez portu** (np. ICMP): pakiet bez portu „nie jest portem 53”.
- **Goła nazwa procesu to podciąg**: `--target chrome` złapie też `chromedriver.exe`. Precyzyjnie:
  `--target "re:^chrome\.exe$"`.
- **Zakresy są obustronnie domknięte** (`80-80` = jeden port), jak w nmap/iptables.
- **CLI jest zawsze po angielsku**, niezależnie od języka GUI i systemu.
- **`-q` naprawdę milczy**: przy sukcesie nie wypisze niczego. Wynik odczytaj z kodu wyjścia
  (albo dodaj `--format json`).
- **Uruchomienie bez admina** (i bez `--simulate`) kończy się kodem `7` - nie „ciszą”.
- **Sterownik zablokował plik w `%TEMP%`?** To relikt starych buildów onefile:
  `BeanNetworkTester.exe --cleanup-driver` zwalnia go bez restartu systemu.

## Testy

Silnik jest oddzielony od WinDivert, więc testy działają na każdym systemie (nie wymagają
Windows, admina ani tkintera). Zestaw jest oparty o **pytest**:

```bat
pip install -r requirements-dev.txt
python -m pytest tests
```

Sprawdzają wszystkie mechanizmy: utratę, latencję, jitter, throttling per-kierunek,
uszkodzenia, duplikację, wyrażenia filtrów (listy, zakresy, `!`, `>`, `<`, wildcardy, `re:`, CIDR,
IPv6), celowanie w proces/cel, gubienie SYN, MTU, flapping, wygasanie NAT,
wstrzykiwanie RST, skoki latencji, harmonogram, log połączeń, powtarzalność (seed),
scenariusze, plik konfiguracji, podsumowanie (PL/EN), tłumaczenia UI oraz reprodukcję
(efektywny seed, dziennik zdarzeń, raport i komendę CLI). Osobny test uruchamia też smoke
GUI (`smoke_gui.py`, na podrobionym tkinterze), a konwencje repo (nazewnictwo, brak
tkintera w rdzeniu pakietu) pilnowane są testami.

Osobno pilnowany jest **kontrakt CLI pod CI/CD**:
- `tests/test_cli_runtime.py` - kody wyjścia (0/1/3/4/5/6/130/143), dokładność `--duration`
  (nie „do najbliższego raportu”), rozdział stdout/stderr, NDJSON, `-q`/`-v`, `--dry-run`,
  `--print-config`, `--min-packets`, precedencja `--duration` względem pliku konfiguracji.
  Pętla raportowania dostaje wstrzykiwany zegar, więc testy czasu trwania idą w mikrosekundach;
- `tests/test_failsafe.py` - sesja sama się zatrzymuje po `duration`, martwy wątek przechwytujący
  powoduje *fail-open* (zwolnienie sterownika = sieć wraca), `_tick` GUI przeżywa wyjątek,
  wątek celowania nigdy nie dotyka tkintera, zamknięcie okna zawsze zwalnia silnik.

Te same testy odpala automatycznie **GitHub Actions** przy każdym pushu
(`.github/workflows/ci.yml`): macierz Linux + **Windows**, smoke GUI, asercje kodów wyjścia,
sprawdzenie NDJSON, a na koniec **build `.exe` i smoke zbudowanego pliku** (`--version`,
`--simulate`, błędna konfiguracja → kod 3) z artefaktem do pobrania.

## Struktura projektu

Kod jest podzielony na pakiet `beantester/`; w korzeniu zostaje cienki launcher
`bean_network_tester.py`, dzięki czemu wszystkie dotychczasowe komendy (README,
raporty reprodukcji, PyInstaller) działają bez zmian.

```
bean_network_tester.py   launcher + fasada zgodności (re-eksport publicznego API)
beantester/              pakiet z implementacją
  core.py                czysty rdzeń decyzyjny per-pakiet (BeanCore)
  engine.py              wątki przechwytywania/wstrzykiwania, statystyki (BeanEngine)
  matchers.py            wyrażenia filtrów (lista/zakres/!/>/</wildcard/re:) - wspólne
                         dla pól proces, IP i port; jedno źródło prawdy
  settings.py            model ustawień, plik konfiguracji, apply_settings
  scenario.py  presets.py  filters.py  summary.py  repro.py  views.py
  cli.py                 parser argumentów, tryb CLI i dyspozytor GUI/CLI
  exitcodes.py           KODY WYJŚCIA - kontrakt CLI z CI/CD (jedno źródło prawdy)
  clilog.py              wyjście CLI: log na stderr ([bean]), dane na stdout (tekst/NDJSON)
  winenv.py              Windows: admin, elewacja (UAC), odłączenie konsoli, DPI
  driver.py              cykl życia sterownika WinDivert + --doctor / --cleanup-driver
  fields.py              REJESTR PÓL - jedno źródło prawdy: typ, etykieta, jednostka,
                         zakres, sekcja formularza, zakres profilu, flaga CLI
  validators.py          walidacja liczb i zakresów (wspólna dla GUI, CLI i pliku konfiguracji)
  portmap.py             tabela gniazd: lokalny port -> PID (iphlpapi/ctypes; fallback psutil)
  targeting.py           żywy zbiór portów celu: odświeżanie na chybieniu + drzewo procesów
  jsonfile.py            zapis atomowy + kwarantanna uszkodzonych plików użytkownika
  crashlog.py            logger awarii: quiet/note/once, kwarantanna, raport w tle
  appinfo.py             tożsamość aplikacji i odczyt wersji (jedno źródło: VERSION.txt)
  i18n.py  paths.py  utils.py  processes.py  synthetic.py  legal.py  scenario_runner.py
  gui/                   interfejs tkinter
    app.py               kompozycja okna, stan, log, start/stop, dirty-state
    form.py              formularz generowany z fields.FIELD_DEFS
    scaling.py           DPI, skalowane piksele, geometria okna/wykresu/tooltipa
    wheel.py             normalizacja kółka myszy (czysta funkcja)
    scrollable.py        ScrollableFrame + JEDEN globalny dispatcher kółka
    accordion.py         zwijane sekcje
    ui_state.py          zapamiętywanie stanu okna (bean_network_tester_ui.json)
    prefs.py             preferencje GUI (język, wykres, log) zapisywane w ui.json
    pages/               rejestr stron: control, stats (3 podzakładki), conns
    panels/              okna wtórne: „O programie”, „Ustawienia” i dziennik zdarzeń
    widgets/             SortableTree (sortowanie, diff wierszy, Ctrl+C, limit szerokości kolumn)
    model_worker.py      przebudowa modelu tabeli w wątku roboczym (UI się nie blokuje)
    windows.py           bazowa klasa i rejestr okien wtórnych
    dialogs.py           ciemne, wbudowane odpowiedniki messagebox/simpledialog
    rates.py             uśrednianie przepustowości (czysty, testowalny helper)
    theme.py  chart.py  tooltip.py  profiles.py  icon.py  labels.py
lang/                    tłumaczenia (en, pl)
tests/                   testy pytest
smoke_gui.py             smoke GUI na podrobionym tkinterze
BeanNetworkTester.spec   przepis builda (onedir, konsola, asInvoker)
```

## Jak to działa (skrót)

Rdzeń `BeanCore.decide()` to czysta funkcja decydująca o losie pakietu w kolejności:
celowanie → tryb LAN → blokada (firewall) → NAT → RST → flapping → MTU → SYN → utrata → uszkodzenie →
opóźnienie/jitter/skok → limit przepustowości (token bucket z ograniczonym buforem, ew. z harmonogramu) → duplikacja.
Wątek przechwytujący czyta pakiety i wykonuje decyzję; wątek re-injektujący wysyła je w
wyznaczonym momencie. Wszystkie losowania idą przez jeden generator (opcjonalnie seedowany).

## Uwagi i ograniczenia

- Modyfikuje ruch pasujący do filtra; do węższych testów użyj „Celuj w proces” lub „Celuj w cel”.
- Ping = ICMP: żeby na niego wpłynąć, wybierz filtr obejmujący ICMP.
- Limit prędkości słabo widać na pingu (małe pakiety) - testuj pobieraniem pliku.
- Realne przechwytywanie i wstrzykiwanie RST działa tylko na Windowsie z WinDivert; logikę
  potwierdzają testy uruchamiane wszędzie.
- Narzędzie do testowania własnych aplikacji i sieci.

### Zachowania, o których warto wiedzieć

- **Harmonogram zapętla się** - po ostatnim kroku wraca do pierwszego (`2:100:0, 2:500:0`
  to na przemian 2 s po 100 KB/s i 2 s po 500 KB/s, bez końca). Zastosowanie harmonogramu
  w trakcie sesji startuje cykl od kroku pierwszego.
- **Harmonogram ma pierwszeństwo przed stałym limitem** - gdy pole „Harmonogram” nie jest
  puste, wartości „Pobieranie/Wysyłanie” (KB/s) są ignorowane, bo przepustowość bierze się
  z kolejnych kroków harmonogramu.
- **Harmonogram jest opcjonalny, ale musi być poprawny** - puste pole = brak harmonogramu,
  natomiast błędny wpis (np. `1:100`, `2:abc:0`) jest zgłaszany jako błąd: GUI nie wystartuje
  sesji, a CLI kończy się komunikatem. Nic nie jest po cichu pomijane.
- **Wyrażenia filtrów są walidowane** - niepoprawny wpis w polu proces/IP/port (np. `999.1.1.1`,
  `2000-1000`, `>chrome`, `re:[`) jest zgłaszany jako błąd zamiast cicho nie działać: w GUI pole
  robi się czerwone z powodem pod spodem, a CLI kończy się komunikatem `error: ...`.
  Porównanie adresów jest niewrażliwe na zapis (skrócony i pełny zapis IPv6 to ten sam adres).
- **Pozytywy sumują się, wykluczenia odejmują** - `80,443,!8080` znaczy „80 lub 443, ale nie 8080”,
  a samo `!53` znaczy „wszystko oprócz 53”. Kolejność członów nie ma znaczenia. Szczegóły i przypadki
  brzegowe: [Składnia filtrów](#składnia-filtrów-proces--ip--port).
- **Zakresy są obustronnie domknięte** - `8000-8100` obejmuje 8000 i 8100 (jak w nmap/iptables),
  a `80-80` to dokładnie jeden port.
- **IP i port w „Celuj w cel” łączy AND** - ustawienie obu pól zawęża do ruchu, który spełnia
  **oba** warunki naraz.
- **Bardzo niski limit prędkości = realne straty** - przy domyślnym buforze (1000 ms) nadmiar
  ponad limit, gdy bufor się zapełni, jest porzucany i liczony jako **„Odrzuc. przez limit”**
  (osobny licznik, nie „Utracone”) - tak zachowuje się zatkane łącze, więc efektywna strata bywa
  wtedy wyższa niż ustawiony procent „Utrata”. Dopiero przy `--buffer 0` (bufor bez limitu)
  kolejka narzędzia rośnie aż do twardego limitu **20 000** pakietów i nadmiar leci jako
  **„Bufor przepełn.”**.
- **Puste pole Seed = losowy seed** - program i tak wylosuje konkretną wartość i pokaże ją
  w panelu sesji. W plikach konfiguracji wartość `-1` oznacza „losuj”, więc `-1` nie da się
  użyć jako zwykłego ziarna (każda inna liczba, także ujemna, działa normalnie).
- **Celowanie w proces obejmuje procesy potomne** - gniazdo należy do celu, jeśli pasuje proces,
  **który je otworzył, albo dowolny jego przodek**. Dlatego `chrome.exe` (albo PID okna przeglądarki)
  łapie też jej proces sieciowy - a on właśnie trzyma wszystkie połączenia. Jawne wykluczenie ma
  pierwszeństwo: `chrome, !chromedriver` nie wciągnie `chromedriver` przez rodzica.
- **Celowanie w proces to wyścig z systemem (i tak zostanie)** - WinDivert daje pakiet, nie PID,
  więc proces ustalamy z tabeli gniazd po **lokalnym porcie**. Tabela jest odświeżana ~3× na sekundę
  i **dodatkowo natychmiast, gdy pojawi się nieznany port**, więc świeżo otwarte połączenie zaczyna
  być psute po kilkudziesięciu ms. Pierwszy pakiet zupełnie nowego połączenia może się prześliznąć -
  to ograniczenie metody, nie błąd.
- **Celowanie, które nic nie łapie, nic nie psuje** - jeśli żaden działający proces nie pasuje do
  wyrażenia, ruch przechodzi nietknięty. Program mówi o tym wprost (czerwona notka pod polem
  i wpis w logu), bo „przebieg, w którym nic się nie zepsuło” wygląda identycznie jak „aplikacja
  wytrzymała”.
- **Goła nazwa procesu to podciąg** - `chrome` łapie też `chromedriver.exe`. To zachowanie
  zachowane celowo (zgodność ze starymi konfiguracjami); po precyzję sięgnij po `re:^chrome\.exe$`
  albo wykluczenie `chrome, !chromedriver`.
- **Statystyki i Połączenia pokazują CAŁY przechwycony ruch** - to, co przepuszcza filtr „Ruch do
  modyfikacji”. Celowanie (proces / IP / port) decyduje wyłącznie o tym, **co zostanie zepsute**,
  a nie o tym, co jest widoczne w tabelach i licznikach.
- **Limit prędkości kształtuje ŚREDNIĄ** - kubełek tokenów przepuszcza chwilowe skoki, więc
  „Szczyt pobierania/wysyłania” (uśredniany w oknie 1 s) potrafi być odrobinę wyższy niż ustawiony
  limit. Duplikaty są liczone do limitu (drugi egzemplarz też jedzie łączem).
- **Okno ma maksymalny rozmiar i nie da się go zmaksymalizować** - układ (dwie kolumny + pasek logu)
  przestaje mieć sens rozciągnięty na 4K, więc rozmiar jest ograniczony, a przycisk maksymalizacji
  usunięty.
- **Czas trwania liczy się od STARTU** - zmiana pola w trakcie sesji nic nie robi (jak filtr ruchu);
  po osiągnięciu limitu program po prostu robi STOP i zostawia wyniki na ekranie.
- **STOP porzuca pakiety czekające w kolejce opóźnienia** - koniec sesji jest natychmiastowy.
  Przy dużym `latency` to widać jako jednorazową „dziurę”; to nie jest błąd.
- **Awaria w środku sesji zawsze kończy się przywróceniem sieci** - jeśli wątek przechwytujący
  padnie, silnik sam robi STOP i zwalnia sterownik (*fail-open*), zamiast trzymać otwarty uchwyt,
  do którego nikt nie sięga (to była realna droga do „user nagle nie ma internetu”).
  Powód trafia do logu i do dziennika zdarzeń.
- **Zamknięcie programu zwalnia sterownik WinDivert** - nie po każdej sesji (restart sesji ma być
  natychmiastowy), ale **raz, przy wyjściu z programu**. Dopóki sterownik jest załadowany, jądro
  trzyma otwarty `WinDivert64.sys` leżący obok exe - i wtedy **katalogu programu nie da się usunąć,
  nawet gdy wygląda na pusty** (Windows pozwala skasować plik z otwartym uchwytem: znika z listy,
  ale zostaje w stanie *pending delete* i blokuje katalog). Gdyby coś zostało, ratunek bez restartu:
  `BeanNetworkTester.exe --cleanup-driver` (albo `sc stop WinDivert` + `sc delete WinDivert`).
- **„Czas trwania” i „Ruch do modyfikacji” są brane pod uwagę tylko przy STARCIE** - dlatego
  w trakcie sesji oba są **zablokowane** (edytowalne pole, które nic nie robi, jest gorsze niż
  wyszarzone).

## Współtworzenie

Wkład jest mile widziany. Plik [CONTRIBUTING.md](CONTRIBUTING.md) opisuje, jak uruchomić testy
i jakich konwencji trzyma się projekt; zajrzyj też do [kodeksu postępowania](CODE_OF_CONDUCT.md).
Zgłoszenia błędów i propozycje funkcji idą przez szablony zgłoszeń, a sprawy bezpieczeństwa
obsługuje prywatnie [polityka bezpieczeństwa](SECURITY.md).

## Wsparcie projektu

Projekt rozwija **DonislawDev** i jest darmowy. Jeśli narzędzie oszczędza Ci czas i chcesz,
żeby powstawały kolejne funkcje, możesz **dobrowolnie** wesprzeć jego rozwój:

**https://donislawdev.com/support/**

Wsparcie jest w pełni opcjonalne - cała funkcjonalność działa bez niego. W programie
prowadzi tam przycisk **„Wesprzyj projekt”** (nagłówek okna).

## Autor

**DonislawDev** - https://donislawdev.com/

Bean Network Tester powstaje w procesie wspomaganym AI.

## Licencja

Bean Network Tester to **wolne oprogramowanie open source** na licencji **GNU General
Public License w wersji 3 (GPLv3)** - patrz plik [LICENSE](LICENSE) (tekst licencji
wyłącznie po angielsku).

Krótko: wolno używać do dowolnych celów (prywatnych i komercyjnych), badać jak
działa i zmieniać go, a także rozpowszechniać kopie - również zmodyfikowane -
pod warunkiem przekazywania programu dalej na tych samych warunkach GPLv3 i
udostępnienia odpowiadającego kodu źródłowego. Program dostarczany jest „AS IS”,
bez gwarancji i bez odpowiedzialności autora. Autorem jest **DonislawDev**.

## Komponenty firm trzecich

Program korzysta z bibliotek innych autorów, na ich własnych licencjach - m.in.
**WinDivert** i **PyDivert** na licencji **LGPLv3**, **psutil** (BSD),
**CPython** (PSF), **Tcl/Tk** i bootloader **PyInstaller**. Pełna lista, wersje i
adresy źródeł są w [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), a pełne
teksty licencji w katalogu `licenses/`. Z poziomu programu: `--license` (CLI)
albo przycisk **O programie** w interfejsie.

Biblioteki LGPL (WinDivert, PyDivert) można podmienić na własne, zgodne
interfejsowo wersje - dlatego program jest budowany jako **onedir**, ze
sterownikiem i bibliotekami leżącymi obok pliku .exe. GPLv3 jest zgodna z
licencjami tych komponentów, a licencja projektu nie ogranicza praw z nich
wynikających.

## Prywatność: brak telemetrii

Bean Network Tester **nie wysyła nigdzie żadnych danych**. Nie ma w nim
telemetrii, sprawdzania aktualizacji ani żadnego klienta sieciowego. Narzędzie
przechwytuje ruch sieciowy na Twoim komputerze - i te dane **nigdy go nie
opuszczają**. Jedyne połączenie wychodzące, jakie program może wykonać, to
otwarcie strony wsparcia w Twojej przeglądarce, i tylko gdy sam klikniesz
odpowiedni przycisk.

## Uwaga: SmartScreen i antywirusy

Plik .exe nie jest (jeszcze) podpisany certyfikatem, a jednocześnie prosi o
uprawnienia administratora i ładuje sterownik sieciowy - dlatego Windows
SmartScreen może pokazać ostrzeżenie „Nieznany wydawca”, a niektóre antywirusy
mogą zgłosić fałszywy alarm. Sam sterownik **WinDivert jest podpisany cyfrowo
przez jego autora**. Sumę kontrolną SHA-256 wydania (`SHA256SUMS.txt`) możesz
porównać, żeby potwierdzić, że plik nie został zmodyfikowany.

Dokumentacja po angielsku: [README.md](README.md).
