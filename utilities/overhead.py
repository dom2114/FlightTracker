from threading import Thread, Lock
from time import sleep
from types import SimpleNamespace
import csv
import io
import math
import os
import re

import requests

from utilities.flightnumber_enricher import (
    FlightNumberEnricher,
    needs_enrichment,
)

try:
    from config import MIN_ALTITUDE
except (ModuleNotFoundError, NameError, ImportError):
    MIN_ALTITUDE = 0  # feet

try:
    from config import SEARCH_RADIUS_NM
except (ModuleNotFoundError, NameError, ImportError):
    SEARCH_RADIUS_NM = 100  # nautical miles, max 250 on airplanes.live

try:
    from config import AIRLABS_API_KEY
except (ModuleNotFoundError, NameError, ImportError):
    AIRLABS_API_KEY = ""

try:
    from config import AIRLABS_MAX_CALLS_PER_DAY
except (ModuleNotFoundError, NameError, ImportError):
    AIRLABS_MAX_CALLS_PER_DAY = 30

RETRIES = 3
RATE_LIMIT_DELAY = 1
MAX_FLIGHT_LOOKUP = 5
MAX_ALTITUDE = 60000  # feet
EARTH_RADIUS_KM = 6371
BLANK_FIELDS = ["", "N/A", "NONE"]
HTTP_TIMEOUT = 10

LIVE_URL = "https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}"
ROUTE_URL = "https://vrs-standing-data.adsb.lol/routes/{prefix}/{cs}.json"
AIRLINES_URL = "https://raw.githubusercontent.com/vradarserver/standing-data/main/airlines/schema-01/airlines.csv"
CALLSIGN_RE = re.compile(r"^([A-Z]{3})(\d+[A-Z0-9]*)$")

AIRLINES_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_airlines_cache.csv"
)

try:
    from config import LOCATION_HOME
    LOCATION_DEFAULT = LOCATION_HOME
except (ModuleNotFoundError, NameError, ImportError):
    LOCATION_DEFAULT = [51.509865, -0.118092, 0.0]


def _haversine_nm(lat1, lon1, lat2, lon2):
    R_NM = 3440.065  # Earth radius in nautical miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def distance_from_flight_to_home(flight, home=LOCATION_DEFAULT):
    def polar_to_cartesian(lat, long, alt):
        DEG2RAD = math.pi / 180
        return [
            alt * math.cos(DEG2RAD * lat) * math.sin(DEG2RAD * long),
            alt * math.sin(DEG2RAD * lat),
            alt * math.cos(DEG2RAD * lat) * math.cos(DEG2RAD * long),
        ]

    def feet_to_meters_plus_earth(altitude_ft):
        altitude_km = 0.0003048 * altitude_ft
        return altitude_km + EARTH_RADIUS_KM

    try:
        (x0, y0, z0) = polar_to_cartesian(
            flight.latitude,
            flight.longitude,
            feet_to_meters_plus_earth(flight.altitude),
        )

        (x1, y1, z1) = polar_to_cartesian(*home)

        dist = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)

        return dist

    except AttributeError:
        return 1e6


def _to_flight(ac):
    alt = ac.get("alt_baro")
    if alt == "ground" or alt is None:
        return None
    try:
        altitude = int(alt)
    except (TypeError, ValueError):
        return None

    lat = ac.get("lat")
    lon = ac.get("lon")
    if lat is None or lon is None:
        return None

    callsign = (ac.get("flight") or "").strip()
    plane = (ac.get("desc") or "").strip()
    registration = (ac.get("r") or "").strip()
    hex_code = (ac.get("hex") or "").strip()

    speed = ac.get("gs")
    try:
        speed = int(round(float(speed))) if speed is not None else 0
    except (TypeError, ValueError):
        speed = 0

    track = ac.get("track")
    try:
        heading = f"{int(round(float(track))) % 360:03d}"
    except (TypeError, ValueError):
        heading = "000"

    vertical = ac.get("baro_rate")
    if vertical is None:
        vertical = ac.get("geom_rate")
    if vertical is None:
        vertical = 0

    return SimpleNamespace(
        latitude=lat,
        longitude=lon,
        altitude=altitude,
        callsign=callsign,
        vertical_speed=vertical,
        plane=plane,
        registration=registration,
        speed=speed,
        heading=heading,
        hex=hex_code,
    )


class Overhead:
    def __init__(self):
        self._lock = Lock()
        self._data = []
        self._new_data = False
        self._processing = False
        self._route_cache = {}
        self._iata_map = self._load_airline_iata_map()
        self._enricher = FlightNumberEnricher(
            api_key=AIRLABS_API_KEY,
            max_calls_per_day=AIRLABS_MAX_CALLS_PER_DAY,
        )

    def _load_airline_iata_map(self):
        csv_text = None

        # Try network first so we get fresh data when online.
        try:
            r = requests.get(AIRLINES_URL, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            csv_text = r.text
            try:
                with open(AIRLINES_CACHE_PATH, "w", encoding="utf-8") as fh:
                    fh.write(csv_text)
            except OSError:
                pass
        except requests.RequestException:
            pass

        # Fall back to the on-disk cache from a previous successful fetch.
        if csv_text is None and os.path.exists(AIRLINES_CACHE_PATH):
            try:
                with open(AIRLINES_CACHE_PATH, "r", encoding="utf-8") as fh:
                    csv_text = fh.read()
            except OSError:
                pass

        if csv_text is None:
            print(
                "FlightTracker: could not load airline ICAO→IATA mapping "
                "(no network and no cached copy). Flight numbers will fall back "
                "to raw ICAO callsigns."
            )
            return {}

        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            mapping = {}
            for row in reader:
                icao = (row.get("ICAO") or "").strip().upper()
                iata = (row.get("IATA") or "").strip().upper()
                if icao and iata:
                    mapping[icao] = iata
            if not mapping:
                print(
                    "FlightTracker: airline IATA mapping parsed but is empty; "
                    "flight numbers will fall back to raw ICAO callsigns."
                )
            return mapping
        except (ValueError, csv.Error):
            print(
                "FlightTracker: failed to parse airline IATA mapping CSV; "
                "flight numbers will fall back to raw ICAO callsigns."
            )
            return {}

    def _callsign_to_flnum(self, callsign):
        if not callsign:
            return ""
        cs = callsign.upper()
        m = CALLSIGN_RE.match(cs)
        if not m:
            return callsign
        icao, suffix = m.group(1), m.group(2)
        iata = self._iata_map.get(icao)
        if not iata:
            return callsign
        return f"{iata}{suffix}"

    def grab_data(self):
        Thread(target=self._grab_data).start()

    def _fetch_aircraft(self):
        url = LIVE_URL.format(
            lat=LOCATION_DEFAULT[0],
            lon=LOCATION_DEFAULT[1],
            nm=SEARCH_RADIUS_NM,
        )
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json().get("ac", []) or []

    def _lookup_route(self, callsign):
        if not callsign or len(callsign) < 2:
            return ("", "")
        if callsign in self._route_cache:
            return self._route_cache[callsign]

        result = ("", "")
        try:
            url = ROUTE_URL.format(prefix=callsign[:2], cs=callsign)
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                payload = r.json()
                iata = payload.get("_airport_codes_iata", "") or ""
                if "-" in iata:
                    origin, destination = iata.split("-", 1)
                    result = (origin.strip(), destination.strip())
        except (requests.RequestException, ValueError):
            pass

        self._route_cache[callsign] = result
        return result

    def _grab_data(self):
        with self._lock:
            self._new_data = False
            self._processing = True

        data = []

        try:
            aircraft = self._fetch_aircraft()

            home_lat, home_lon = LOCATION_DEFAULT[0], LOCATION_DEFAULT[1]
            flights = [_to_flight(ac) for ac in aircraft]
            flights = [
                f for f in flights
                if f is not None
                and MIN_ALTITUDE < f.altitude < MAX_ALTITUDE
                and _haversine_nm(home_lat, home_lon, f.latitude, f.longitude) <= SEARCH_RADIUS_NM
            ]
            flights = sorted(flights, key=lambda f: distance_from_flight_to_home(f))

            for flight in flights[:MAX_FLIGHT_LOOKUP]:
                # Pace per-route HTTP calls
                sleep(RATE_LIMIT_DELAY)

                origin, destination = self._lookup_route(flight.callsign)

                plane = flight.plane if flight.plane.upper() not in BLANK_FIELDS else ""
                origin = origin if origin.upper() not in BLANK_FIELDS else ""
                destination = destination if destination.upper() not in BLANK_FIELDS else ""
                callsign = flight.callsign if flight.callsign.upper() not in BLANK_FIELDS else ""
                registration = flight.registration if flight.registration.upper() not in BLANK_FIELDS else ""

                # Compressed callsigns (RYR/EZY/EXS-style with letters in the
                # suffix) make the cheap prefix swap synthetic — e.g. EXS17TU
                # is not Jet2's marketing flight LS17TU. Try airlabs by hex,
                # and if no real flight number comes back, fall back to the
                # raw callsign rather than fabricate one.
                if needs_enrichment(callsign):
                    enriched = None
                    if self._enricher.enabled and flight.hex:
                        enriched = self._enricher.lookup(flight.hex, callsign)
                    flnum = enriched or callsign
                else:
                    flnum = self._callsign_to_flnum(callsign)

                data.append(
                    {
                        "plane": plane,
                        "origin": origin,
                        "destination": destination,
                        "vertical_speed": flight.vertical_speed,
                        "altitude": flight.altitude,
                        "callsign": callsign,
                        "registration": registration,
                        "flnum": flnum,
                        "speed": flight.speed,
                        "heading": flight.heading,
                    }
                )

            with self._lock:
                self._new_data = True
                self._processing = False
                self._data = data

        except requests.RequestException:
            with self._lock:
                self._new_data = False
                self._processing = False

    @property
    def new_data(self):
        with self._lock:
            return self._new_data

    @property
    def processing(self):
        with self._lock:
            return self._processing

    @property
    def data(self):
        with self._lock:
            self._new_data = False
            return self._data

    @property
    def data_is_empty(self):
        return len(self._data) == 0


if __name__ == "__main__":

    o = Overhead()
    o.grab_data()
    while o.processing:
        print("processing...")
        sleep(1)

    print(o.data)
