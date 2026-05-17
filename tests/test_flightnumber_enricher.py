import unittest

from utilities.flightnumber_enricher import FlightNumberEnricher, _today_utc


class FlightNumberEnricherTests(unittest.TestCase):
    def test_lookup_serves_cached_value_even_when_daily_cap_is_reached(self):
        enricher = FlightNumberEnricher(api_key="test-key", max_calls_per_day=0)
        enricher._cache[("EZY76HE", _today_utc())] = "U28706"

        self.assertEqual(enricher.lookup("400001", "EZY76HE"), "U28706")


if __name__ == "__main__":
    unittest.main()
