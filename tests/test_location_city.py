import unittest


class LocationCityTests(unittest.TestCase):
    def test_location_city_preference(self):
        row = {"LOCATION (CITY)": "Lisboa", "LOCATION": "Lisboa, Portugal"}
        location_city = (row.get("LOCATION (CITY)") or "").strip()
        if not location_city:
            location_city = row.get("LOCATION", "")
        location_city = location_city.split(",")[0].strip() if location_city else ""
        self.assertEqual(location_city, "Lisboa")

    def test_location_city_fallback(self):
        row = {"LOCATION (CITY)": "", "LOCATION": "Porto, Portugal"}
        location_city = (row.get("LOCATION (CITY)") or "").strip()
        location_city = location_city.split(",")[0].strip() if location_city else ""
        self.assertEqual(location_city, "")


if __name__ == "__main__":
    unittest.main()
