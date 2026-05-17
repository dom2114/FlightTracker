"""Optional marketing-flight-number enrichment via airlabs.co.

The cheap ICAO->IATA prefix swap done in `overhead.py` is correct for legacy
carriers (BA, LH, AA) but wrong for low-cost carriers (Ryanair, easyJet,
Wizz) which use compressed operational callsigns whose suffix doesn't match
the marketing flight number passengers see (e.g. EZY76HE = U28706, not
U276HE).

This module looks up the marketing number on airlabs.co by aircraft hex
code and caches the result by (callsign, UTC date) so repeated sightings
of the same flight cost zero additional API calls.

Free tier: 1000 requests/month. We default to a daily cap of 30 to keep
worst-case usage under that limit.
"""

import re
import time
from datetime import datetime, timezone

import requests

AIRLABS_URL = "https://airlabs.co/api/v9/flights"
HTTP_TIMEOUT = 10

CALLSIGN_RE = re.compile(r"^([A-Z]{3})(\d+[A-Z0-9]*)$")


def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def needs_enrichment(callsign):
    """True iff `callsign` is airline-format AND its suffix contains a letter.

    Pure-numeric suffixes (BAW184, DLH918) already give the marketing number
    after the cheap prefix swap, so we never spend an API call on them.
    """
    if not callsign:
        return False
    m = CALLSIGN_RE.match(callsign.upper())
    if not m:
        return False
    suffix = m.group(2)
    return any(ch.isalpha() for ch in suffix)


class FlightNumberEnricher:
    def __init__(self, api_key, max_calls_per_day=30, error_backoff_min=30):
        self._api_key = (api_key or "").strip()
        self._max_calls_per_day = max_calls_per_day
        self._error_backoff_sec = max(60, error_backoff_min * 60)
        self._cache = {}            # (callsign_upper, YYYY-MM-DD) -> flnum or None
        self._calls_by_day = {}     # YYYY-MM-DD -> int
        self._disabled_until = 0.0  # monotonic seconds
        self._cap_warned_for_day = None

    @property
    def enabled(self):
        if not self._api_key:
            return False
        if time.monotonic() < self._disabled_until:
            return False
        if self._calls_by_day.get(_today_utc(), 0) >= self._max_calls_per_day:
            today = _today_utc()
            if self._cap_warned_for_day != today:
                print(
                    f"FlightTracker: airlabs daily cap of "
                    f"{self._max_calls_per_day} reached. Enrichment paused "
                    f"until UTC midnight."
                )
                self._cap_warned_for_day = today
            return False
        return True

    def lookup(self, hex_code, callsign):
        """Return marketing flight number for the given aircraft, or None."""
        if not hex_code or not callsign:
            return None

        cache_key = (callsign.upper(), _today_utc())
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self.enabled:
            return None

        try:
            r = requests.get(
                AIRLABS_URL,
                params={"api_key": self._api_key, "hex": hex_code.lower()},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            print(f"FlightTracker: airlabs request failed ({e}); backing off "
                  f"enrichment for {self._error_backoff_sec // 60} min.")
            self._disabled_until = time.monotonic() + self._error_backoff_sec
            return None

        # Count the call against today's quota regardless of outcome.
        today = _today_utc()
        self._calls_by_day[today] = self._calls_by_day.get(today, 0) + 1

        if r.status_code in (401, 403):
            print("FlightTracker: airlabs auth failed (HTTP "
                  f"{r.status_code}). Disabling enrichment for 24h. "
                  "Check AIRLABS_API_KEY in config.py.")
            self._disabled_until = time.monotonic() + 24 * 3600
            return None

        if r.status_code == 429:
            print("FlightTracker: airlabs rate-limited (HTTP 429). "
                  f"Backing off for {self._error_backoff_sec // 60} min.")
            self._disabled_until = time.monotonic() + self._error_backoff_sec
            return None

        if r.status_code != 200:
            print(f"FlightTracker: airlabs HTTP {r.status_code}. "
                  f"Backing off enrichment for "
                  f"{self._error_backoff_sec // 60} min.")
            self._disabled_until = time.monotonic() + self._error_backoff_sec
            return None

        try:
            payload = r.json()
        except ValueError:
            self._disabled_until = time.monotonic() + self._error_backoff_sec
            return None

        flights = payload.get("response") or []
        if not flights:
            self._cache[cache_key] = None
            return None

        flnum = (flights[0].get("flight_iata") or "").strip()
        if not flnum:
            self._cache[cache_key] = None
            return None

        self._cache[cache_key] = flnum
        return flnum
