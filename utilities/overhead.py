from threading import Thread, Lock
from time import sleep
from types import SimpleNamespace
import csv
import io
import math
import os
import re

import requests

try:
    from config import MIN_ALTITUDE
except (ModuleNotFoundError, NameError, ImportError):
    MIN_ALTITUDE = 0  # feet

try:
    from config import SEARCH_RADIUS_NM
except (ModuleNotFoundError, NameError, ImportError):
    SEARCH_RADIUS_NM = 100  # nautical miles, max 250 on airplanes.live

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
    LOCATION_DEFAULT = [51.509865, -0.118092, EARTH_RADIUS_KM]

try:
    from config import ZONE_HOME
    ZONE_DEFAULT = ZONE_HOME
except (ModuleNotFoundError, NameError, ImportError):
    ZONE_DEFAULT = None  # No rectangle filter — radius alone defines the area


def _in_zone(flight, zone):
    if zone is None:
        return True
    try:
        return (
            zone["br_y"] <= flight.latitude <= zone["tl_y"]
            and zone["tl_x"] <= flight.longitude <= zone["br_x"]
        )
    except (KeyError, TypeError):
        return True


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
    )


class Overhead:
    def __init__(self):
        self._lock = Lock()
        self._data = []
        self._new_data = False
        self._processing = False
        self._route_cache = {}
        self._iata_map = self._load_airline_iata_map()

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

            flights = [_to_flight(ac) for ac in aircraft]
            flights = [
                f for f in flights
                if f is not None
                and f.altitude < MAX_ALTITUDE
                and f.altitude > MIN_ALTITUDE
                and _in_zone(f, ZONE_DEFAULT)
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
