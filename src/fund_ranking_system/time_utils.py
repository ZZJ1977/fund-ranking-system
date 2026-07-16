from __future__ import annotations

from datetime import datetime, timedelta, timezone


LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
LEGACY_TIMEZONE = timezone.utc


def local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def now_text() -> str:
    return local_now().isoformat(sep=" ", timespec="seconds")


def display_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    parsed = _parse_time(text)
    if parsed is None:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LEGACY_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(text: str) -> datetime | None:
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
