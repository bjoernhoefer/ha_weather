"""Mapping helpers shared by the providers."""

from __future__ import annotations

from typing import Optional

#: WMO weather interpretation codes used by Open-Meteo based providers.
WMO_CODES = {
    0: "clear",
    1: "mostly-clear",
    2: "partlycloudy",
    3: "cloudy",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    56: "freezing-drizzle",
    57: "freezing-drizzle",
    61: "rainy",
    63: "rainy",
    65: "pouring",
    66: "freezing-rain",
    67: "freezing-rain",
    71: "snowy",
    73: "snowy",
    75: "snowy",
    77: "snowy",
    80: "rainy",
    81: "rainy",
    82: "pouring",
    85: "snowy",
    86: "snowy",
    95: "lightning",
    96: "lightning-rainy",
    99: "lightning-rainy",
}


def condition_from_wmo(code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    return WMO_CODES.get(int(code), "unknown")


def normalize_condition(raw: Optional[str]) -> Optional[str]:
    """Map a free text provider condition onto Home Assistant vocabulary."""
    if not raw:
        return None
    text = raw.lower()
    if "thunder" in text:
        return "lightning-rainy" if "rain" in text else "lightning"
    if "snow" in text or "sleet" in text or "blizzard" in text:
        return "snowy"
    if "drizzle" in text:
        return "drizzle"
    if "heavy rain" in text or "pouring" in text:
        return "pouring"
    if "rain" in text or "shower" in text:
        return "rainy"
    if "fog" in text or "mist" in text:
        return "fog"
    if "partly" in text or "fair" in text:
        return "partlycloudy"
    if "cloud" in text or "overcast" in text:
        return "cloudy"
    if "clear" in text or "sun" in text:
        return "clear"
    return "unknown"
