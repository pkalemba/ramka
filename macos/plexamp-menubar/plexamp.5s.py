#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Plexamp Now Playing - wtyczka do SwiftBar / xbar.
# Pokazuje w pasku menu macOS utwor aktualnie grany w Plexampie.
#
# <bitbar.title>Plexamp Now Playing</bitbar.title>
# <bitbar.version>1.0.0</bitbar.version>
# <bitbar.author>ramka</bitbar.author>
# <bitbar.desc>Aktualnie grany utwor z Plexampa w pasku menu.</bitbar.desc>
# <bitbar.dependencies>python3</bitbar.dependencies>
#
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.environment>[VAR_PLEX_URL: http://localhost:32400, VAR_PLEX_TOKEN: , VAR_MAX_LENGTH: 45]</swiftbar.environment>
#
# Konfiguracja: config.json w tym samym katalogu co ten plik (patrz README.md)

import errno
import json
import os
import shlex
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Konfiguracja lezy obok skryptu (w katalogu wtyczek SwiftBara).
# Wariant z kropka przydaje sie, gdy SwiftBar probuje uruchomic config.json jak wtyczke.
CONFIG_NAMES = ("config.json", ".plexamp-menubar.json")
DEFAULT_CONFIG_PATH = Path(__file__).parent / CONFIG_NAMES[0]

DEFAULTS = {
    # Adres serwera Plex Media Server (ten, z ktorego gra Plexamp).
    "plex_url": "http://localhost:32400",
    # Token X-Plex-Token. Zamiast wpisywac go tutaj mozna uzyc "token_cmd".
    "plex_token": "",
    # Komenda zwracajaca token na stdout, np. odczyt z Keychaina.
    "token_cmd": "",
    # Nazwy odtwarzaczy, ktore nas interesuja (Player.product / Player.title).
    # Pusta lista = dowolny odtwarzacz.
    "players": ["Plexamp"],
    # Ograniczenie do jednego uzytkownika Plex, pusty string = dowolny.
    "user": "",
    # Tylko muzyka (type == "track"). False = takze filmy i seriale.
    "music_only": True,
    # Maksymalna dlugosc tekstu w pasku menu (0 = bez obcinania).
    "max_length": 45,
    # Gdy nic nie gra: True = ukryj ikone, False = pokaz sama ikone.
    "hide_when_idle": True,
    # Czy pokazywac utwor zapauzowany.
    "show_paused": True,
    "icon_playing": "♪",  # ♪
    "icon_paused": "⏸",  # ⏸
    "title_format": "{artist} – {title}",
    "timeout": 4.0,
}

ENV_PREFIXES = ("VAR_", "PLEXAMP_MENUBAR_")
BOOL_KEYS = {"music_only", "hide_when_idle", "show_paused"}
INT_KEYS = {"max_length"}
FLOAT_KEYS = {"timeout"}
LIST_KEYS = {"players"}


# ===== KONFIGURACJA =====


def _coerce(key, value):
    """Zamienia wartosc (najczesciej string ze zmiennej srodowiskowej) na typ z DEFAULTS."""
    if key in BOOL_KEYS and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "tak")
    if key in INT_KEYS and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
    if key in FLOAT_KEYS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
    if key in LIST_KEYS and isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


def load_config(env=None, config_data=None):
    """Laczy DEFAULTS + plik konfiguracyjny + zmienne srodowiskowe (env wygrywa)."""
    env = os.environ if env is None else env
    cfg = dict(DEFAULTS)

    if config_data:
        for key, value in config_data.items():
            if key in cfg:
                cfg[key] = _coerce(key, value)

    for key in DEFAULTS:
        for prefix in ENV_PREFIXES:
            env_key = prefix + key.upper()
            if env.get(env_key, "") != "":
                cfg[key] = _coerce(key, env[env_key])
                break

    cfg["plex_url"] = str(cfg["plex_url"]).rstrip("/")
    return cfg


def config_candidates(env=None):
    """Kolejnosc szukania config.json: zmienna srodowiskowa, katalog skryptu,
    katalog skryptu po rozwinieciu dowiazan (gdy wtyczka jest symlinkiem)."""
    env = os.environ if env is None else env
    override = env.get("PLEXAMP_MENUBAR_CONFIG", "")
    if override:
        return [Path(override)]
    directories = [Path(__file__).parent]
    resolved = Path(__file__).resolve().parent
    if resolved not in directories:
        directories.append(resolved)
    return [directory / name for directory in directories for name in CONFIG_NAMES]


def active_config_path(env=None):
    """Plik konfiguracyjny, ktory faktycznie zostanie uzyty (albo domyslna sciezka)."""
    candidates = config_candidates(env)
    return next((item for item in candidates if item.is_file()), candidates[0])


def read_config_file(path=None, env=None):
    if path is None:
        path = active_config_path(env)
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ConfigError("Blad pliku %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ConfigError("Plik %s musi zawierac obiekt JSON" % path)
    return data


class ConfigError(Exception):
    pass


class PlexError(Exception):
    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


def resolve_token(cfg, runner=None):
    """Token z konfiguracji albo z komendy (np. `security find-generic-password -w ...`)."""
    if cfg.get("plex_token"):
        return str(cfg["plex_token"]).strip()
    command = cfg.get("token_cmd")
    if not command:
        return ""
    runner = runner or (
        lambda cmd: subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=5
        ).stdout
    )
    try:
        return (runner(command) or "").strip()
    except Exception as exc:  # noqa: BLE001 - komenda uzytkownika, kazdy blad to brak tokenu
        raise ConfigError("token_cmd (%s) nie zadzialalo: %s" % (shlex.quote(command), exc))


# ===== PLEX API =====


SANDBOX_HINT = (
    "SwiftBar nie ma dostepu do sieci, choc skrypt uruchomiony recznie dziala.\n"
    "System Settings > Privacy & Security > Local Network > wlacz SwiftBar\n"
    "(pomaga tez wylaczenie i ponowne wlaczenie przelacznika).\n"
    "Wersja SwiftBara z Mac App Store dziala w sandboksie - wersja z\n"
    "`brew install --cask swiftbar` nie ma tego ograniczenia."
)

REFUSED_HINT = (
    "Nikt nie slucha na tym porcie. Sprawdz, czy Plex Media Server dziala\n"
    "i czy port w `plex_url` sie zgadza (domyslnie 32400)."
)


def explain_network_error(reason):
    """Zamienia przyczyne bledu polaczenia na (opis, podpowiedz)."""
    code = getattr(reason, "errno", None)
    text = str(getattr(reason, "strerror", None) or reason)

    if code == errno.EPERM or "not permitted" in text.lower():
        return "macOS zablokowal polaczenie", SANDBOX_HINT
    if code == errno.EACCES:
        return "Brak uprawnien do polaczenia", SANDBOX_HINT
    if code == errno.ECONNREFUSED or "refused" in text.lower():
        return "Polaczenie odrzucone", REFUSED_HINT
    if isinstance(reason, socket.gaierror) or code == socket.EAI_NONAME:
        return "Nie mozna rozwiazac nazwy hosta", "Sprawdz `plex_url` w config.json."
    if isinstance(reason, (socket.timeout, TimeoutError)) or code == errno.ETIMEDOUT:
        return "Przekroczono limit czasu", "Serwer nie odpowiada - sprawdz siec i `timeout`."
    return text, None


def url_variants(base_url):
    """Dla `localhost` doklada wariant 127.0.0.1 - pod SwiftBarem bywa roznica."""
    variants = [base_url]
    parts = urllib.parse.urlsplit(base_url)
    if parts.hostname == "localhost":
        netloc = "127.0.0.1" + (":%d" % parts.port if parts.port else "")
        variants.append(urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", "")))
    return variants


def fetch_sessions(cfg, token, opener=None):
    """Zwraca liste sesji z /status/sessions serwera Plex."""
    opener = opener or urllib.request.urlopen
    last_error = None

    for base_url in url_variants(cfg["plex_url"]):
        url = base_url + "/status/sessions"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Plex-Token": token,
                "X-Plex-Client-Identifier": "plexamp-menubar",
                "X-Plex-Product": "Plexamp Menubar",
            },
        )
        try:
            with opener(request, timeout=cfg["timeout"]) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise PlexError(
                    "Nieprawidlowy token Plex (401)",
                    "Token wygasl albo jest z innego konta - wygeneruj nowy.",
                )
            raise PlexError("HTTP %s z %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            description, hint = explain_network_error(exc.reason)
            last_error = PlexError(
                "%s: %s (%s)" % (description, cfg["plex_url"], exc.reason), hint
            )
            continue
        except ValueError:
            raise PlexError(
                "Serwer nie zwrocil JSON-a",
                "Czy pod %s naprawde stoi Plex Media Server?" % cfg["plex_url"],
            )
        except OSError as exc:
            description, hint = explain_network_error(exc)
            last_error = PlexError("%s: %s" % (description, cfg["plex_url"]), hint)
            continue

        container = payload.get("MediaContainer") or {}
        return container.get("Metadata") or []

    raise last_error


def matches_player(session, players):
    if not players:
        return True
    player = session.get("Player") or {}
    haystack = " ".join(
        str(player.get(key, "")) for key in ("product", "title", "device", "platform")
    ).lower()
    return any(name.lower() in haystack for name in players)


def matches_user(session, user):
    if not user:
        return True
    account = session.get("User") or {}
    return str(account.get("title", "")).lower() == user.lower()


def pick_session(sessions, cfg):
    """Wybiera sesje do pokazania: najpierw grajaca, potem zapauzowana."""
    candidates = []
    for session in sessions or []:
        if cfg["music_only"] and session.get("type") != "track":
            continue
        if not matches_player(session, cfg["players"]):
            continue
        if not matches_user(session, cfg["user"]):
            continue
        state = str((session.get("Player") or {}).get("state", "")).lower()
        if state == "paused" and not cfg["show_paused"]:
            continue
        candidates.append((0 if state == "playing" else 1, session))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def describe(session):
    """Normalizuje sesje Plex do plaskiego slownika."""
    player = session.get("Player") or {}
    account = session.get("User") or {}
    return {
        "title": session.get("title") or "",
        "artist": session.get("grandparentTitle") or session.get("originalTitle") or "",
        "album": session.get("parentTitle") or "",
        "year": session.get("parentYear") or session.get("year") or "",
        "state": str(player.get("state", "")).lower(),
        "player": player.get("title") or player.get("product") or "",
        "product": player.get("product") or "",
        "user": account.get("title") or "",
        "offset_ms": int(session.get("viewOffset") or 0),
        "duration_ms": int(session.get("duration") or 0),
        "key": session.get("key") or "",
        "rating_key": session.get("ratingKey") or "",
    }


# ===== RENDEROWANIE =====


def format_time(milliseconds):
    seconds = max(int(milliseconds or 0) // 1000, 0)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    return "%d:%02d" % (minutes, seconds)


def progress_bar(offset_ms, duration_ms, width=16):
    if not duration_ms:
        return ""
    filled = int(round(width * min(max(offset_ms / duration_ms, 0.0), 1.0)))
    return "█" * filled + "░" * (width - filled)


def truncate(text, max_length):
    if not max_length or len(text) <= max_length:
        return text
    return text[: max(max_length - 1, 1)].rstrip() + "…"


def format_menu_title(track, cfg):
    text = cfg["title_format"].format(
        artist=track["artist"],
        title=track["title"],
        album=track["album"],
        player=track["player"],
    )
    text = " ".join(text.split())
    text = text.strip(" –-")
    icon = cfg["icon_paused"] if track["state"] == "paused" else cfg["icon_playing"]
    return ("%s %s" % (icon, truncate(text, cfg["max_length"]))).strip()


def escape(text):
    """SwiftBar traktuje '|' jako separator parametrow."""
    return str(text).replace("|", "│")


def param_value(text):
    """Wartosc parametru w cudzyslowie - bez cudzyslowow, pipe'ow i nowych linii."""
    cleaned = str(text).replace('"', "'").replace("|", "│")
    return " ".join(cleaned.split())


def render_track(track, cfg):
    lines = [escape(format_menu_title(track, cfg))]
    lines.append("---")
    if track["artist"]:
        lines.append("%s | font=Menlo" % escape(track["artist"]))
    lines.append("%s | font=Menlo" % escape(track["title"]))
    if track["album"]:
        album = track["album"]
        if track["year"]:
            album = "%s (%s)" % (album, track["year"])
        lines.append("%s | color=gray font=Menlo" % escape(album))
    if track["duration_ms"]:
        lines.append(
            "%s %s / %s | color=gray font=Menlo"
            % (
                progress_bar(track["offset_ms"], track["duration_ms"]),
                format_time(track["offset_ms"]),
                format_time(track["duration_ms"]),
            )
        )
    lines.append("---")
    label = track["player"] or track["product"] or "Plexamp"
    if track["user"]:
        label = "%s · %s" % (label, track["user"])
    lines.append("%s | color=gray" % escape(label))
    lines.append("Otworz Plexamp | bash=/usr/bin/open param1=-a param2=Plexamp terminal=false")
    copy_text = " - ".join(part for part in (track["artist"], track["title"]) if part)
    lines.append(
        'Kopiuj tytul | bash=/usr/bin/pbcopy stdin="%s" terminal=false' % param_value(copy_text)
    )
    lines.append("Odswiez | refresh=true")
    return "\n".join(lines)


def render_idle(cfg):
    if cfg["hide_when_idle"]:
        return ""
    lines = ["%s | color=gray" % cfg["icon_playing"], "---", "Nic nie gra | color=gray"]
    lines.append("Otworz Plexamp | bash=/usr/bin/open param1=-a param2=Plexamp terminal=false")
    lines.append("Odswiez | refresh=true")
    return "\n".join(lines)


def diagnose_menu_line(label="Diagnostyka w Terminalu"):
    """Uruchamia ten sam plik z --diagnose w oknie Terminala."""
    return '%s | bash="%s" param1="%s" param2=--diagnose terminal=true refresh=false' % (
        label,
        param_value(sys.executable or "/usr/bin/python3"),
        param_value(Path(__file__).resolve()),
    )


def render_error(message, cfg, hint=None):
    lines = ["⚠︎ | color=orange", "---", escape(message) + " | color=orange"]
    if hint:
        for line in hint.splitlines():
            lines.append("%s | color=gray font=Menlo" % escape(line))
    lines.append("---")
    lines.append("Konfiguracja: %s | color=gray" % escape(active_config_path()))
    lines.append(diagnose_menu_line())
    lines.append("Odswiez | refresh=true")
    return "\n".join(lines)


SETUP_HINT = (
    "Utworz config.json obok wtyczki:\n"
    '{\n  "plex_url": "http://localhost:32400",\n  "plex_token": "TWOJ_TOKEN"\n}'
)


def build_output(cfg, token, opener=None):
    if not token:
        return render_error("Brak tokenu Plex", cfg, SETUP_HINT)
    sessions = fetch_sessions(cfg, token, opener=opener)
    session = pick_session(sessions, cfg)
    if session is None:
        return render_idle(cfg)
    return render_track(describe(session), cfg)


# ===== DIAGNOSTYKA =====


def tcp_check(host, port, timeout=3.0):
    """Zwraca (ok, opis) dla surowego polaczenia TCP - omija warstwe HTTP."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "OK"
    except OSError as exc:
        description, _ = explain_network_error(exc)
        return False, description


def diagnose(stream=None):
    """Wypisuje, co widzi wtyczka - to samo srodowisko, w ktorym uruchamia ja SwiftBar."""
    out = stream or sys.stdout
    say = lambda text="": print(text, file=out)  # noqa: E731

    say("=== Plexamp menubar - diagnostyka ===")
    say("python:        %s" % (sys.executable or "?"))
    say("wersja:        %s" % sys.version.split()[0])
    say("wtyczka:       %s" % Path(__file__).resolve())
    say("katalog roboczy: %s" % Path.cwd())
    say("sandbox:       %s" % (os.environ.get("APP_SANDBOX_CONTAINER_ID") or "brak zmiennej"))
    say("SwiftBar:      %s" % (os.environ.get("SWIFTBAR_VERSION") or "uruchomione poza SwiftBarem"))
    say()

    say("Szukane pliki konfiguracyjne:")
    for candidate in config_candidates():
        say("  %s %s" % ("[jest]" if candidate.is_file() else "[brak]", candidate))

    try:
        config_data = read_config_file()
    except ConfigError as exc:
        say("BLAD: %s" % exc)
        return 1

    cfg = load_config(config_data=config_data)
    say("uzyty plik:    %s" % active_config_path())
    say("plex_url:      %s" % cfg["plex_url"])
    say("players:       %s" % (cfg["players"] or "[wszystkie]"))
    say()

    try:
        token = resolve_token(cfg)
    except ConfigError as exc:
        say("BLAD tokenu: %s" % exc)
        return 1
    say("token:         %s" % ("jest (%d znakow)" % len(token) if token else "BRAK"))
    if not token:
        say(SETUP_HINT)
        return 1
    say()

    say("Test polaczenia TCP:")
    for base_url in url_variants(cfg["plex_url"]):
        parts = urllib.parse.urlsplit(base_url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ok, description = tcp_check(parts.hostname, port, cfg["timeout"])
        say("  %s %s:%s - %s" % ("[ok] " if ok else "[nie]", parts.hostname, port, description))
    say()

    say("Zapytanie do Plexa:")
    try:
        sessions = fetch_sessions(cfg, token)
    except PlexError as exc:
        say("  BLAD: %s" % exc)
        if exc.hint:
            say()
            for line in exc.hint.splitlines():
                say("  %s" % line)
        return 1

    say("  sesji lacznie: %d" % len(sessions))
    for item in sessions:
        player = item.get("Player") or {}
        say(
            "  - typ=%s product=%s state=%s | %s - %s"
            % (
                item.get("type"),
                player.get("product"),
                player.get("state"),
                item.get("grandparentTitle"),
                item.get("title"),
            )
        )
    picked = pick_session(sessions, cfg)
    say()
    say("Po filtrach (players=%s, music_only=%s): %s" % (
        cfg["players"], cfg["music_only"], "brak dopasowania" if picked is None else "jest"
    ))
    if picked is not None:
        say()
        say("W pasku menu pojawi sie:")
        say("  %s" % format_menu_title(describe(picked), cfg))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--diagnose" in argv:
        return diagnose()

    try:
        cfg = load_config(config_data=read_config_file())
        token = resolve_token(cfg)
        output = build_output(cfg, token)
    except ConfigError as exc:
        output = render_error(str(exc), load_config(), SETUP_HINT)
    except PlexError as exc:
        output = render_error(str(exc), load_config(), exc.hint)
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
