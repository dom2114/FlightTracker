import unittest
from threading import Lock
from types import SimpleNamespace

from utilities import overhead


class OverheadRadiusTests(unittest.TestCase):
    def test_haversine_uses_nautical_miles(self):
        self.assertAlmostEqual(
            overhead._haversine_nm(0.0, 0.0, 0.0, 1.0),
            60.04,
            places=1,
        )

    def test_to_flight_rejects_invalid_coordinates(self):
        self.assertIsNone(
            overhead._to_flight(
                {
                    "alt_baro": 1000,
                    "lat": "not-a-latitude",
                    "lon": 0,
                    "flight": "BAD1",
                }
            )
        )

    def test_distance_sort_prefers_nearby_plane_over_lower_far_plane(self):
        home = [0.0, 0.0, 0.0]
        near_high = SimpleNamespace(latitude=0.0, longitude=1.0 / 60.0, altitude=40000)
        far_low = SimpleNamespace(latitude=0.0, longitude=20.0 / 60.0, altitude=0)

        self.assertLess(
            overhead.distance_from_flight_to_home(near_high, home),
            overhead.distance_from_flight_to_home(far_low, home),
        )

    def test_grab_data_drops_aircraft_outside_search_radius(self):
        old_home = overhead.LOCATION_DEFAULT
        old_radius = overhead.SEARCH_RADIUS_NM
        old_min_altitude = overhead.MIN_ALTITUDE
        old_sleep = overhead.sleep

        overhead.LOCATION_DEFAULT = [0.0, 0.0, 0.0]
        overhead.SEARCH_RADIUS_NM = 10
        overhead.MIN_ALTITUDE = 0
        overhead.sleep = lambda _: None

        try:
            aircraft = [
                {
                    "alt_baro": 1000,
                    "lat": 0.0,
                    "lon": 5.0 / 60.0,
                    "flight": "INR1",
                    "desc": "A320",
                    "r": "G-INR",
                    "hex": "400001",
                },
                {
                    "alt_baro": 1000,
                    "lat": 0.0,
                    "lon": 11.0 / 60.0,
                    "flight": "OUT1",
                    "desc": "B738",
                    "r": "G-OUT",
                    "hex": "400002",
                },
            ]

            tracker = overhead.Overhead.__new__(overhead.Overhead)
            tracker._lock = Lock()
            tracker._data = []
            tracker._new_data = False
            tracker._processing = False
            tracker._route_cache = {}
            tracker._iata_map = {}
            tracker._enricher = SimpleNamespace(enabled=False)
            tracker._fetch_aircraft = lambda: aircraft
            tracker._lookup_route = lambda callsign: ("", "")

            tracker._grab_data()

            self.assertEqual([flight["callsign"] for flight in tracker.data], ["INR1"])
        finally:
            overhead.LOCATION_DEFAULT = old_home
            overhead.SEARCH_RADIUS_NM = old_radius
            overhead.MIN_ALTITUDE = old_min_altitude
            overhead.sleep = old_sleep


if __name__ == "__main__":
    unittest.main()
