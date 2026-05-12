# Calendar + Countdown Renderer for ESPHome + Waveshare 7.5" e-paper
# Endpoints:
#   GET /calendar.png   - miesięczny kalendarz z eventami HA
#   GET /countdown.png  - odliczanie dni do daty
#   GET /health         - health check

import requests
from flask import Flask, send_file, request
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta, date
import calendar
import io
import logging
from dateutil.parser import isoparse

# ===== KONFIGURACJA =====
# Zmienne środowiskowe ustawiane przez run.sh z options.json (addon HA).
# W trybie lokalnym wpisz swoje wartości poniżej jako fallback.
import os

HA_URL = os.environ.get("HA_URL", "https://hassio.pawel.sh")
HA_TOKEN = os.environ.get(
    "HA_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI5Y2I5ZTVhOTE0ZTE0MmYxODRhMGJkY2ZiZTdkMjc4NSIsImlhdCI6MTc2NjEzODA2MCwiZXhwIjoyMDgxNDk4MDYwfQ.em4_MzkP90uZxFV18-UQSoE6uBVT1EFaiMTkSrS0xNw",
)

HA_HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

# Wymiary ekranu Waveshare 7.5"
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
BG_COLOR = (255, 255, 255)
FG_COLOR = (0, 0, 0)
GRID_COLOR = (0, 0, 0)
WEEKEND_BG = (240, 240, 240)

SHOW_ONLY_DAYS_WITH_EVENTS = True
SHOW_TODAY_PANEL = "only_if_events"

CALENDARS = [
    "calendar.praca",
    "calendar.igi",
    "calendar.swieta_w_polsce",
]

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== FONTS =====

def load_font(font_name: str, size: int):
    font_paths = [
        f"./fonts/{font_name}",
        f"/app/fonts/{font_name}",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    logger.warning(f"Font {font_name} not found, using default")
    return ImageFont.load_default()


def load_font_bold(size: int):
    return load_font("NotoSans-Bold.ttf", size)


def load_font_regular(size: int):
    return load_font("NotoSans.ttf", size)

# ===== CALENDAR HELPERS =====

def get_calendar_events(calendar_entity: str, start: datetime, end: datetime) -> list:
    try:
        cal_id = calendar_entity.split(".")[-1]
        url = f"{HA_URL}/api/calendars/calendar.{cal_id}?start={start.isoformat()}Z&end={end.isoformat()}Z"
        logger.info(f"Fetching events from {calendar_entity}...")
        resp = requests.get(url, headers=HA_HEADERS, timeout=10)
        if resp.status_code == 200:
            events = resp.json()
            logger.info(f"Got {len(events)} events from {calendar_entity}")
            return events
        else:
            logger.warning(f"HA API error for {calendar_entity}: {resp.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error fetching calendar {calendar_entity}: {e}")
        return []


def add_icon_for_calendar(cal_entity):
    icons = {
        "calendar.igi": "[I]",
        "calendar.praca": "[W]",
        "calendar.swieta_w_polsce": "[S]",
    }
    return icons.get(cal_entity, "[*]")


def events_to_day_map(events: dict, year: int, month: int) -> dict:
    by_day = {}
    for cal_entity, evlist in events.items():
        for event in evlist:
            try:
                start = event.get("start", {})
                end = event.get("end", {})
                icon = add_icon_for_calendar(cal_entity)
                summary = (event.get("summary", "Event") or "Event").strip()
                if len(summary) > 30:
                    summary = summary[:27] + "..."

                if start.get("dateTime"):
                    try:
                        sdt = isoparse(start["dateTime"])
                    except Exception:
                        sdt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
                    if sdt.year == year and sdt.month == month:
                        time_str = sdt.strftime("%H:%M")
                        by_day.setdefault(sdt.day, []).append(f"{time_str} {icon} {summary}")

                elif start.get("date"):
                    s_date = datetime.fromisoformat(start["date"]).date()
                    try:
                        e_date = datetime.fromisoformat(end.get("date", start["date"])).date()
                    except Exception:
                        e_date = s_date
                    current = s_date
                    while current < e_date:
                        if current.year == year and current.month == month:
                            by_day.setdefault(current.day, []).append(f"00: {icon} {summary}")
                        current += timedelta(days=1)

            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue

    for d, lst in by_day.items():
        try:
            lst.sort(key=lambda s: (s[:5] if len(s) >= 5 and s[0].isdigit() else "99:99", s))
        except Exception:
            pass

    return by_day

# ===== CALENDAR RENDERER =====

def render_month_calendar(year: int, month: int, events_by_day: dict,
                          show_only_with_events: bool = True,
                          show_today_panel: str = "only_if_events",
                          invert: bool = False) -> Image.Image:
    if invert:
        bg_color = (0, 0, 0)
        fg_color = (255, 255, 255)
        grid_color = (255, 255, 255)
        weekend_bg = (50, 50, 50)
    else:
        bg_color = BG_COLOR
        fg_color = FG_COLOR
        grid_color = GRID_COLOR
        weekend_bg = WEEKEND_BG

    import calendar as cal_module
    if show_only_with_events:
        days_to_display = sorted([d for d in events_by_day.keys() if d > 0])
        grid_cells = None
        grid_mode_full_month = False
    else:
        num_days_in_month = cal_module.monthrange(year, month)[1]
        first_weekday = datetime(year, month, 1).weekday()
        grid_cells = [None] * first_weekday + list(range(1, num_days_in_month + 1))
        grid_mode_full_month = True

    if grid_mode_full_month:
        cols = 7
        rows = (len(grid_cells) + cols - 1) // cols
    else:
        if not days_to_display:
            img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), bg_color)
            draw = ImageDraw.Draw(img)
            draw.text((50, 200), "Brak eventów", fill=fg_color, font=load_font_regular(16))
            return img
        cols = min(5, max(1, len(days_to_display)))
        rows = (len(days_to_display) + cols - 1) // cols

    font_title_big = load_font_bold(16)
    font_daynum = load_font_regular(13)
    font_daynum_bold = load_font_bold(13)
    font_small = load_font_regular(10)

    img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)

    today = datetime.now()
    today_day = today.day
    today_events = events_by_day.get(today_day, [])

    show_panel = (show_today_panel == "always") or (show_today_panel == "only_if_events" and bool(today_events))
    divider_x = int(SCREEN_WIDTH * 0.75) if show_panel else SCREEN_WIDTH

    margin_h = 15
    margin_v = 20
    header_height = 30
    available_w = divider_x - 2 * margin_h - 2
    available_h = SCREEN_HEIGHT - header_height - 2 * margin_v
    cell_w = max(70, available_w // cols)
    cell_h = max(50, available_h // rows)

    left = margin_h
    top = header_height + margin_v
    right = left + cell_w * cols
    bottom = top + cell_h * rows

    month_names_pl = [
        "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
        "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
    ]
    title = f"{month_names_pl[month - 1]} {year}"
    bbox = draw.textbbox((0, 0), title, font=font_title_big)
    title_w = bbox[2] - bbox[0]
    draw.text(((divider_x - title_w) // 2, 5), title, fill=fg_color, font=font_title_big)

    for c in range(cols + 1):
        x = left + c * cell_w
        draw.line([(x, top), (x, bottom)], fill=grid_color, width=1)
    for r in range(rows + 1):
        y = top + r * cell_h
        draw.line([(left, y), (right, y)], fill=grid_color, width=1)

    iter_cells = enumerate(grid_cells) if grid_mode_full_month else enumerate(days_to_display)
    dow_abbr = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]

    for idx, day in iter_cells:
        row = idx // cols
        col = idx % cols
        cell_x = left + col * cell_w
        cell_y = top + row * cell_h

        dow = col if grid_mode_full_month else datetime(year, month, day).weekday()
        is_weekend = dow >= 5

        if is_weekend:
            draw.rectangle(
                [(cell_x + 1, cell_y + 1), (cell_x + cell_w - 1, cell_y + cell_h - 1)],
                fill=weekend_bg,
            )

        if day is None:
            continue

        is_past = (year == today.year and month == today.month and day < today.day)
        is_today = (year == today.year and month == today.month and day == today.day)
        day_font = font_daynum_bold if is_today else font_daynum
        label = f"{dow_abbr[dow]} {day}"
        draw.text((cell_x + 3, cell_y + 3), label, fill=fg_color, font=day_font)

        if is_past:
            bbox = draw.textbbox((cell_x + 3, cell_y + 3), label, font=day_font)
            mid_y = (bbox[1] + bbox[3]) // 2
            draw.line([(bbox[0], mid_y), (bbox[2], mid_y)], fill=fg_color, width=1)

        max_char = (cell_w - 6) // 7
        y_ev = cell_y + 20
        line_h = 9
        for ev in events_by_day.get(day, [])[:2]:
            if y_ev + line_h > cell_y + cell_h - 2:
                break
            text = ev[4:] if ev.startswith("00: ") else ev
            words = text.split()
            line = ""
            for word in words:
                if len(line) + len(word) + 1 <= max_char:
                    line = (line + " " + word).strip()
                else:
                    if line and y_ev + line_h <= cell_y + cell_h - 2:
                        draw.text((cell_x + 3, y_ev), line, fill=fg_color, font=font_small)
                        y_ev += line_h
                    line = word
            if line and y_ev + line_h <= cell_y + cell_h - 2:
                if len(line) > max_char - 1:
                    line = line[:max_char - 2] + ".."
                draw.text((cell_x + 3, y_ev), line, fill=fg_color, font=font_small)
                y_ev += line_h

        if len(events_by_day.get(day, [])) > 2 and y_ev + line_h <= cell_y + cell_h - 2:
            draw.text((cell_x + 3, y_ev), "...", fill=fg_color, font=font_small)

    if show_panel:
        draw.line([(divider_x, 0), (divider_x, SCREEN_HEIGHT)], fill=grid_color, width=2)
        right_left = divider_x + 15
        right_top = 5
        font_right_title = load_font_bold(14)
        day_names_pl = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]
        header = f"{day_names_pl[today.weekday()]} {today_day}.{today.month}"
        draw.text((right_left, right_top), header, fill=fg_color, font=font_right_title)
        y_pos = right_top + 25
        for ev in today_events:
            if y_pos + 12 > SCREEN_HEIGHT - 10:
                break
            draw.text((right_left, y_pos), ev[:28], fill=fg_color, font=font_small)
            y_pos += 12

    return img

# ===== COUNTDOWN RENDERER =====

MONTHS_PL_GEN = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia"
]


def render_countdown(title: str, target_date: date,
                     start_date: date = None, invert: bool = False) -> Image.Image:
    """Renderuje odliczanie dni do target_date dla wyświetlacza 800x480.

    Układ (z góry na dół):
        Tytuł → linia → duża liczba dni → etykieta DNI → [pasek postępu] → linia → data
    """
    bg = (0, 0, 0) if invert else (255, 255, 255)
    fg = (255, 255, 255) if invert else (0, 0, 0)

    img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    today = date.today()
    days_left = (target_date - today).days

    # ----- Tytuł -----
    font_title = load_font_bold(44)
    t_bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = t_bbox[2] - t_bbox[0]
    draw.text(((SCREEN_WIDTH - tw) // 2, 18), title, fill=fg, font=font_title)

    sep1_y = 78
    draw.line([(60, sep1_y), (SCREEN_WIDTH - 60, sep1_y)], fill=fg, width=2)

    # ----- Duża liczba -----
    num_str = str(max(0, days_left))
    num_size = 200 if len(num_str) <= 2 else (165 if len(num_str) == 3 else 130)
    font_num = load_font_bold(num_size)
    n_bbox = draw.textbbox((0, 0), num_str, font=font_num)
    nw = n_bbox[2] - n_bbox[0]
    nh = n_bbox[3] - n_bbox[1]
    # Wyśrodkuj poziomo; zacznij tuż pod separatorem
    nx = (SCREEN_WIDTH - nw) // 2 - n_bbox[0]
    ny = sep1_y + 8 - n_bbox[1]
    draw.text((nx, ny), num_str, fill=fg, font=font_num)

    # ----- Etykieta DNI / DZIEŃ -----
    label = "DZIEŃ" if days_left == 1 else "DNI"
    font_label = load_font_bold(46)
    l_bbox = draw.textbbox((0, 0), label, font=font_label)
    lw = l_bbox[2] - l_bbox[0]
    label_y = ny + nh + n_bbox[1] + 4
    draw.text(((SCREEN_WIDTH - lw) // 2, label_y), label, fill=fg, font=font_label)

    bottom_area_start = SCREEN_HEIGHT - 75
    sep2_y = bottom_area_start - 5

    # ----- Pasek postępu (jeśli podano start_date) -----
    if start_date and start_date < target_date:
        total = (target_date - start_date).days
        elapsed = (today - start_date).days
        progress = max(0.0, min(1.0, elapsed / total))

        bar_w = SCREEN_WIDTH - 140
        bar_h = 18
        bar_x = 70
        bar_y = sep2_y - 38
        draw.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], outline=fg, width=2)
        fill_w = int(bar_w * progress)
        if fill_w > 3:
            draw.rectangle(
                [(bar_x + 2, bar_y + 2), (bar_x + fill_w - 2, bar_y + bar_h - 2)],
                fill=fg,
            )
        pct_str = f"{int(progress * 100)}%"
        font_pct = load_font_regular(13)
        p_bbox = draw.textbbox((0, 0), pct_str, font=font_pct)
        draw.text(
            ((SCREEN_WIDTH - (p_bbox[2] - p_bbox[0])) // 2, bar_y + bar_h + 3),
            pct_str, fill=fg, font=font_pct,
        )

    draw.line([(60, sep2_y), (SCREEN_WIDTH - 60, sep2_y)], fill=fg, width=2)

    # ----- Data docelowa -----
    date_str = f"{target_date.day} {MONTHS_PL_GEN[target_date.month - 1]} {target_date.year}"
    font_date = load_font_regular(30)
    d_bbox = draw.textbbox((0, 0), date_str, font=font_date)
    dw = d_bbox[2] - d_bbox[0]
    draw.text(
        ((SCREEN_WIDTH - dw) // 2, bottom_area_start + 8),
        date_str, fill=fg, font=font_date,
    )

    return img

# ===== ENDPOINTS =====

@app.route("/calendar.png")
def calendar_png():
    """Miesięczny kalendarz z eventami HA.

    Query params:
      year, month          – domyślnie bieżący
      full_month=true      – pełny miesiąc zamiast tylko dni z eventami
      today_panel=always   – zawsze pokazuj panel dzisiejszego dnia
      invert=true          – odwróć kolory
    """
    try:
        now = datetime.now()
        year = int(request.args.get("year", now.year))
        month = int(request.args.get("month", now.month))
        full_month = request.args.get("full_month", "false").lower() == "true"
        today_panel = request.args.get("today_panel", "only_if_events")
        invert = request.args.get("invert", "false").lower() == "true"

        logger.info(f"Rendering calendar {month}/{year}")

        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 2) if month == 12 else datetime(year, month + 1, 2)

        all_events = {cal: get_calendar_events(cal, start, end) for cal in CALENDARS}
        events_by_day = events_to_day_map(all_events, year, month)

        img = render_month_calendar(
            year, month, events_by_day,
            show_only_with_events=not full_month,
            show_today_panel=today_panel,
            invert=invert,
        )

        bio = io.BytesIO()
        img.save(bio, "PNG")
        bio.seek(0)
        return send_file(bio, mimetype="image/png")

    except Exception as e:
        logger.error(f"Error rendering calendar: {e}", exc_info=True)
        return f"Error: {e}", 500


@app.route("/countdown.png")
def countdown_png():
    """Odliczanie dni do podanej daty.

    Query params (wymagane):
      date=RRRR-MM-DD   – data docelowa

    Query params (opcjonalne):
      title=tekst       – tytuł wyświetlany nad liczbą (domyślnie: "Odliczanie")
      start=RRRR-MM-DD  – data startowa do paska postępu
      invert=true       – białe cyfry na czarnym tle

    Przykłady:
      /countdown.png?date=2026-08-01&title=Do%20wakacji
      /countdown.png?date=2026-12-25&title=Do%20Świąt&start=2026-06-01
      /countdown.png?date=2027-01-01&title=Nowy%20Rok&invert=true
    """
    date_str = request.args.get("date")
    if not date_str:
        return "Brakuje parametru ?date=RRRR-MM-DD", 400

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return "Nieprawidłowy format daty — użyj RRRR-MM-DD", 400

    title = request.args.get("title", "Odliczanie")
    invert = request.args.get("invert", "false").lower() == "true"

    start_date = None
    start_str = request.args.get("start")
    if start_str:
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    logger.info(f"Rendering countdown to {target_date} (title={title!r})")

    img = render_countdown(title, target_date, start_date=start_date, invert=invert)

    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
