# Plexamp w pasku menu macOS

Aktualnie grany utwór z Plexampa wyświetlany w górnym pasku macOS:

```
♪ Queen – Bohemian Rhapsody
```

Po kliknięciu rozwija się menu z wykonawcą, tytułem, albumem, paskiem postępu
i nazwą odtwarzacza.

Zamiast pisać własną aplikację od zera używamy **[SwiftBar](https://github.com/swiftbar/SwiftBar)**
(darmowy, open source, MIT) — to gotowa aplikacja, która potrafi umieścić w pasku menu
wynik dowolnego skryptu. Tutaj dokładamy do niej jeden plik: `plexamp.5s.py`.

Dane pochodzą z API serwera Plex (`/status/sessions`), a nie z prywatnych API macOS —
dzięki temu działa to na wszystkich wersjach systemu (również ≥ 15.4, gdzie Apple
zablokowało `MediaRemote`) i pokazuje też muzykę graną z Plexampa na innym urządzeniu.

## Wymagania

- macOS 12+
- Plexamp odtwarzający muzykę z serwera Plex Media Server
- SwiftBar (`brew install --cask swiftbar`) lub [xbar](https://xbarapp.com)
- Python 3 (systemowy `/usr/bin/python3` wystarczy)

## Instalacja

1. **SwiftBar**

   ```sh
   brew install --cask swiftbar
   ```

   Przy pierwszym uruchomieniu SwiftBar poprosi o wskazanie katalogu z wtyczkami,
   np. `~/.swiftbar-plugins`.

2. **Wtyczka**

   ```sh
   cp macos/plexamp-menubar/plexamp.5s.py ~/.swiftbar-plugins/
   chmod +x ~/.swiftbar-plugins/plexamp.5s.py
   ```

   `5s` w nazwie to interwał odświeżania. Chcesz rzadziej? Zmień nazwę na
   `plexamp.10s.py` albo `plexamp.1m.py`.

3. **Token Plex**

   Token znajdziesz tak: Plex Web → dowolny utwór → `...` → *Get Info* → *View XML* —
   w adresie URL na końcu jest `X-Plex-Token=...`.

   ```sh
   mkdir -p ~/.config/plexamp-menubar
   cat > ~/.config/plexamp-menubar/config.json <<'JSON'
   {
     "plex_url": "http://localhost:32400",
     "plex_token": "TWOJ_TOKEN"
   }
   JSON
   chmod 600 ~/.config/plexamp-menubar/config.json
   ```

   Jeśli serwer Plex stoi na NAS-ie/serwerze, wpisz jego adres, np.
   `"plex_url": "http://192.168.1.10:32400"`.

4. SwiftBar → *Refresh all*. Gdy Plexamp gra, w pasku pojawi się utwór.

### Token w Keychainie (opcjonalnie)

Zamiast trzymać token w pliku:

```sh
security add-generic-password -a "$USER" -s plex-token -w 'TWOJ_TOKEN'
```

i w `config.json`:

```json
{
  "plex_url": "http://localhost:32400",
  "token_cmd": "security find-generic-password -s plex-token -w"
}
```

## Konfiguracja

Wszystkie opcje `config.json` (każdą można też nadpisać zmienną środowiskową
`VAR_<NAZWA>` ustawianą w SwiftBarze):

| Klucz | Domyślnie | Opis |
| --- | --- | --- |
| `plex_url` | `http://localhost:32400` | adres serwera Plex |
| `plex_token` | `""` | token `X-Plex-Token` |
| `token_cmd` | `""` | komenda zwracająca token (np. z Keychaina) |
| `players` | `["Plexamp"]` | które odtwarzacze pokazywać; `[]` = wszystkie |
| `user` | `""` | ogranicz do jednego użytkownika Plex |
| `music_only` | `true` | `false` = pokazuj też filmy i seriale |
| `max_length` | `45` | maksymalna długość tekstu w pasku (`0` = bez limitu) |
| `hide_when_idle` | `true` | `false` = pokaż ikonę, gdy nic nie gra |
| `show_paused` | `true` | czy pokazywać utwór zapauzowany |
| `icon_playing` / `icon_paused` | `♪` / `⏸` | ikony |
| `title_format` | `{artist} – {title}` | dostępne pola: `artist`, `title`, `album`, `player` |
| `timeout` | `4.0` | timeout zapytania HTTP w sekundach |

Przykład — tylko tytuł, krócej, bez pauzy:

```json
{
  "plex_url": "http://localhost:32400",
  "plex_token": "TWOJ_TOKEN",
  "title_format": "{title} · {artist}",
  "max_length": 30,
  "show_paused": false
}
```

## Rozwiązywanie problemów

Uruchom wtyczkę ręcznie — wypisze to samo, co widzi SwiftBar:

```sh
python3 ~/.swiftbar-plugins/plexamp.5s.py
```

- **Pusto** — nic nie gra albo sesja nie pasuje do filtra `players`.
  Sprawdź, co widzi serwer: `curl -s -H 'Accept: application/json' \
  "http://localhost:32400/status/sessions?X-Plex-Token=TOKEN" | python3 -m json.tool`
  i porównaj pole `Player.product` z listą `players`.
- **`Nieprawidlowy token Plex (401)`** — token wygasł albo jest z innego konta.
- **`Brak polaczenia`** — zły `plex_url` lub serwer nieosiągalny z tej sieci.
- **Utwory z lokalnych plików / offline w Plexampie** nie tworzą sesji na serwerze,
  więc się nie pokażą.

## Testy

Logika (konfiguracja, wybór sesji, formatowanie) jest pokryta testami i nie wymaga
macOS ani działającego Plexa:

```sh
cd macos/plexamp-menubar && python3 -m unittest test_plexamp -v
```

## Alternatywy

- **[NowPlaying for Plex](https://github.com/impactcrew/nowplaying-for-plex)** — gotowa
  natywna aplikacja (Swift, MIT) z widżetem w pasku menu i okładką albumu. Zaleta:
  ładniejsza. Wada: nie jest podpisana (trzeba obejść Gatekeepera przy pierwszym
  uruchomieniu) i pokazuje dowolne media Plex, nie tylko Plexampa.
- **[mediaremote-adapter](https://github.com/ungive/mediaremote-adapter)** — czyta systemowe
  „Now Playing”, więc działa z każdym odtwarzaczem, ale opiera się na prywatnym API Apple.
- Wbudowane w macOS **Now Playing** w Centrum sterowania pokazuje Plexampa, ale bez
  tekstu w samym pasku menu.
