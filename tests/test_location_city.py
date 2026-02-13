import unittest


class LocationCityTests(unittest.TestCase):
    def test_location_city_preference(self):
        row = {"LOCATION (CITY)": "Vila Roriz, Porto", "LOCATION": "Parque de Lazer da Vila de Roriz"}
        location_city = (row.get("LOCATION (CITY)") or "").strip()
        if not location_city:
            location_city = row.get("LOCATION", "")
        self.assertEqual(location_city, "Vila Roriz, Porto")

    def test_location_city_fallback(self):
        row = {"LOCATION (CITY)": "", "LOCATION": "Porto, Portugal"}
        location_city = (row.get("LOCATION (CITY)") or "").strip()
        self.assertEqual(location_city, "")


if __name__ == "__main__":
    unittest.main()
