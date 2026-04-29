import unittest
from unittest.mock import patch
import os
import sys

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

try:
    import _2_content_generation as content_generation
    _HAS_DEPS = True
except ModuleNotFoundError:
    _HAS_DEPS = False


class CoordinatesFallbackTests(unittest.TestCase):
    @unittest.skipUnless(_HAS_DEPS, "runtime deps are not available in test env")
    def test_fallback_uses_location_city_when_location_fails(self):
        with patch("_2_content_generation.get_coordinates_from_location") as mocked:
            mocked.side_effect = [(None, None), (40.21, -8.11)]
            lat, lon = content_generation.get_coordinates_with_city_fallback(
                "Santa Comba Dao - Parque Verde",
                "Santa Comba Dao"
            )
            self.assertEqual((lat, lon), (40.21, -8.11))
            self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
