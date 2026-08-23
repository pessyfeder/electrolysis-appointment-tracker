"""Small cross-platform formatting helpers (avoids %-I / %#I strftime quirks)."""
import re


def format_12h(dt) -> str:
    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ampm}"


def format_duration_minutes(total_minutes) -> str:
    """Formats a duration in minutes as '45 min' or, once it reaches an hour,
    as 'x hour(s) x minute(s)' (omitting the minutes part when it's zero)."""
    total_minutes = int(total_minutes)
    if total_minutes < 60:
        return f"{total_minutes} min"
    hours, minutes = divmod(total_minutes, 60)
    text = f"{hours} hour" + ("s" if hours != 1 else "")
    if minutes:
        text += f" {minutes} minute" + ("s" if minutes != 1 else "")
    return text


def format_client_name(first_name, last_name) -> str:
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    if first_name:
        return f"{last_name}, {first_name}"
    return last_name


def digits_only(phone) -> str:
    return re.sub(r"\D", "", phone or "")


def format_phone(phone) -> str:
    """Formats a US-style phone number as (XXX) XXX-XXXX (or with a leading
    +N country code prefix for longer numbers). Returns the input unchanged
    if it doesn't look like a formattable phone number."""
    digits = digits_only(phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return phone or ""


def is_valid_phone(phone) -> bool:
    digits = digits_only(phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return len(digits) == 10
