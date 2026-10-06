"""The day's weather for the top of a packet, in plain words a child can read.

Forecasts come from Open-Meteo (no API key). A family's town or ZIP is turned into rounded
coordinates once, with OpenStreetMap's Nominatim, when they save it on the Family page. If
either service can't be reached the packet is printed without the weather, never held up.
"""

import re
import time
from collections import Counter
from datetime import datetime

import httpx

FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://nominatim.openstreetmap.org/search"
AGENT = "homeschool-packets/1.0 (+https://github.com/tsan400/homeschool)"
FAHRENHEIT = {"us", "lr", "mm", "bs", "bz", "ky", "pw", "fm", "mh"}
DAY_HOURS = range(7, 19)  # what matters for a school day

# WMO weather codes -> (words, icon). Icons are drawn in render.py.
SKY = {0: ("Sunny", "sun"), 1: ("Mostly sunny", "sun"), 2: ("Partly cloudy", "partly"), 3: ("Cloudy", "cloud"),
       45: ("Foggy", "fog"), 48: ("Foggy and frosty", "fog"),
       51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
       56: ("Freezing drizzle", "drizzle"), 57: ("Freezing drizzle", "drizzle"),
       61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
       66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
       71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
       80: ("Showers", "rain"), 81: ("Showers", "rain"), 82: ("Heavy showers", "rain"),
       85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
       95: ("Thunderstorms", "storm"), 96: ("Thunderstorms and hail", "storm"), 99: ("Thunderstorms and hail", "storm")}
ICONS = ("sun", "partly", "cloud", "fog", "drizzle", "rain", "snow", "storm")


TIMEOUT = httpx.Timeout(6, connect=3)


class WeatherError(Exception):
    pass


def _get(client: httpx.Client | None, url: str, **kw) -> httpx.Response:
    """GET with a few quick retries: a dropped connection shouldn't cost a packet its weather."""
    c = client or httpx.Client(timeout=TIMEOUT)
    for attempt in range(3):
        try:
            r = c.get(url, **kw)
            r.raise_for_status()
            return r
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))


def locate(query: str, client: httpx.Client | None = None) -> dict:
    """'Concord, MA' or '01742' -> {place, lat, lon, units}. Coordinates are rounded to about a
    kilometre: plenty for a forecast, and no more precise than it needs to be."""
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    if re.fullmatch(r"\d{5}(-\d{4})?", query.strip()):
        params["countrycodes"] = "us"  # a bare five-digit number is a ZIP code, not a postcode abroad
    try:
        hits = _get(client, GEOCODE, params=params, headers={"User-Agent": AGENT}).json()
    except (httpx.HTTPError, ValueError) as e:
        raise WeatherError(f"couldn't look up that place right now ({e.__class__.__name__})") from e
    if not hits:
        raise WeatherError(f"couldn't find \"{query}\"; try a town and state, or a ZIP code")
    hit, a = hits[0], hits[0].get("address", {})
    town = next((a[k] for k in ("city", "town", "village", "hamlet", "suburb", "municipality", "county") if a.get(k)), None)
    place = ", ".join(x for x in (town, a.get("state") or a.get("country")) if x) or hit["display_name"]
    return {"place": place, "lat": round(float(hit["lat"]), 2), "lon": round(float(hit["lon"]), 2),
            "units": "fahrenheit" if a.get("country_code") in FAHRENHEIT else "celsius"}


def fetch(lat: float, lon: float, day: str, tz: str, units: str, client: httpx.Client | None = None) -> dict:
    """Raw Open-Meteo forecast for one day."""
    us = units == "fahrenheit"
    try:
        r = _get(client, FORECAST, params={
            "latitude": lat, "longitude": lon, "timezone": tz, "start_date": day, "end_date": day,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                     "wind_gusts_10m_max,uv_index_max,sunrise,sunset",
            "hourly": "weather_code,precipitation_probability,temperature_2m",
            "temperature_unit": units, "wind_speed_unit": "mph" if us else "kmh",
            "precipitation_unit": "inch" if us else "mm"})
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise WeatherError(f"no forecast for {day} ({e.__class__.__name__})") from e


def rank(code: int) -> int:
    """How much a kind of weather matters to someone heading outside."""
    return [0, 1, 2, 3, 45, 48, 51, 53, 55, 61, 80, 63, 81, 65, 82, 56, 57, 66, 67, 71, 85, 73, 77, 75, 86, 95, 96, 99].index(code) \
        if code in SKY else 0


def clock(iso: str) -> str:
    t = datetime.fromisoformat(iso)
    return t.strftime("%I:%M %p").lstrip("0").lower().replace(":00 ", " ")


def summarize(data: dict) -> dict:
    """Open-Meteo response -> {sky, icon, high, low, unit, notes, sunrise, sunset}.
    The sky is what the school day looks like, not the worst hour of the night."""
    d, h = data["daily"], data["hourly"]
    us = data["daily_units"]["temperature_2m_max"] == "°F"
    hours = [(datetime.fromisoformat(t).hour, code, p, temp) for t, code, p, temp in
             zip(h["time"], h["weather_code"], h["precipitation_probability"], h["temperature_2m"])]
    day = [x for x in hours if x[0] in DAY_HOURS and x[1] is not None]
    counts = Counter(code for _, code, _, _ in day)
    # The most serious weather that lasts at least two daytime hours (a storm only needs one).
    serious = [c for c in counts if counts[c] >= 2 or c >= 95]
    code = max(serious, key=rank) if serious else d["weather_code"][0]
    if code not in SKY:
        code = d["weather_code"][0] if d["weather_code"][0] in SKY else 3
    sky, icon = SKY[code]
    high, low = round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0])
    wet = [hr for hr, _, p, _ in day if p is not None and p >= 50]
    chance = max((p for _, _, p, _ in day if p is not None), default=0)
    gust = d["wind_gusts_10m_max"][0] or 0
    uv = d["uv_index_max"][0] or 0
    morning = min((temp for hr, _, _, temp in hours if 6 <= hr <= 9 and temp is not None), default=low)

    def f(deg_f):  # thresholds are written in Fahrenheit
        return deg_f if us else (deg_f - 32) * 5 / 9

    def when(hrs):
        if not hrs or (hrs[0] <= 8 and hrs[-1] >= 16):
            return ""
        if hrs[-1] < 12:
            return " this morning"
        start = datetime(2000, 1, 1, hrs[0]).strftime("%I %p").lstrip("0").lower()
        return f" after {start}"

    notes = []
    if icon == "storm":
        notes.append("Thunderstorms possible. Head indoors if you hear thunder.")
    if icon == "snow":
        notes.append(f"Snow likely{when(wet)}. Boots and mittens!")
    elif wet and icon != "storm":
        notes.append(f"Rain likely{when(wet)}. Bring an umbrella.")
    elif chance >= 30 and icon not in ("storm", "snow"):
        notes.append("A chance of a shower. Keep a jacket handy.")
    if morning <= f(32):
        notes.append("Below freezing this morning. Bundle up!")
    elif high >= f(90):
        notes.append("Hot afternoon. Drink plenty of water.")
    elif high - morning >= (22 if us else 12):
        notes.append("Chilly morning, warm afternoon. Wear layers.")
    if gust >= (30 if us else 48):
        notes.append(f"Windy, with gusts to {round(gust)} {'mph' if us else 'km/h'}.")
    if uv >= 7 and icon in ("sun", "partly"):
        notes.append("Strong sun. Wear sunscreen.")
    if icon == "fog" and not notes:
        notes.append("Foggy, so it's hard to see far. Take care near roads.")
    if not notes:
        notes.append({"sun": "A lovely day for a nature walk.", "partly": "A good day to be outside.",
                      "cloud": "A gray day, but dry.", "drizzle": "Damp, but not much rain."}.get(icon, "Dress for the weather."))
    return {"sky": sky, "icon": icon, "high": high, "low": low, "unit": "°F" if us else "°C", "notes": notes[:2],
            "sunrise": clock(d["sunrise"][0]), "sunset": clock(d["sunset"][0])}


def for_family(family, day: str) -> dict | None:
    """The forecast for a family's place on a day, or None if they haven't set a place or it
    can't be had (too far ahead, or no network). Never raises."""
    if family["lat"] is None:
        return None
    try:
        return summarize(fetch(family["lat"], family["lon"], day, family["tz"], family["units"] or "fahrenheit")) \
            | {"place": family["place"]}
    except (WeatherError, KeyError, IndexError, TypeError, ValueError):
        return None
