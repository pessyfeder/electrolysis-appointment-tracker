"""Small cross-platform formatting helpers (avoids %-I / %#I strftime quirks)."""


def format_12h(dt) -> str:
    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ampm}"
