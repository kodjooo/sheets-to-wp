import os
import sys
import types
import unittest
from unittest.mock import patch


RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

# Local stub to avoid dependency on external package in tests.
if "woocommerce" not in sys.modules:
    woocommerce_stub = types.ModuleType("woocommerce")

    class _APIStub:
        def __init__(self, *args, **kwargs):
            pass

    woocommerce_stub.API = _APIStub
    sys.modules["woocommerce"] = woocommerce_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.files = types.SimpleNamespace(create=lambda **kwargs: types.SimpleNamespace(id="file_1"))
    sys.modules["openai"] = openai_stub

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub

if "pytz" not in sys.modules:
    pytz_stub = types.ModuleType("pytz")
    pytz_stub.timezone = lambda _name: None
    sys.modules["pytz"] = pytz_stub

if "_1_google_loader" not in sys.modules:
    gl_stub = types.ModuleType("_1_google_loader")
    gl_stub.load_config = lambda: {}
    gl_stub.load_revised_rows = lambda: []
    gl_stub.load_all_rows = lambda: ([], {})
    gl_stub.update_status_to_published = lambda *args, **kwargs: None
    gl_stub.batch_update_cells = lambda *args, **kwargs: None
    sys.modules["_1_google_loader"] = gl_stub

if "_2_content_generation" not in sys.modules:
    cg_stub = types.ModuleType("_2_content_generation")
    cg_stub.extract_text_from_url = lambda *args, **kwargs: ("", None)
    cg_stub.build_first_assistant_prompt = lambda *args, **kwargs: ""
    cg_stub.validate_source_texts = lambda *args, **kwargs: []
    cg_stub.normalize_regulations_link_block = lambda payload, _url: payload
    cg_stub.call_openai_assistant = lambda *args, **kwargs: None
    cg_stub.call_second_openai_assistant = lambda *args, **kwargs: None
    cg_stub.generate_image = lambda *args, **kwargs: {"url": "", "id": None}
    cg_stub.get_coordinates_with_city_fallback = lambda *args, **kwargs: ("", "")
    cg_stub.translate_title_to_en = lambda text: text
    sys.modules["_2_content_generation"] = cg_stub

if "_3_create_product" not in sys.modules:
    cp_stub = types.ModuleType("_3_create_product")
    cp_stub.create_or_update_product = lambda *args, **kwargs: 0
    cp_stub.get_category_id_by_name = lambda *args, **kwargs: 0
    sys.modules["_3_create_product"] = cp_stub

if "_4_create_translation" not in sys.modules:
    ct_stub = types.ModuleType("_4_create_translation")
    ct_stub.create_or_update_product_pt = lambda *args, **kwargs: 0
    sys.modules["_4_create_translation"] = ct_stub

if "_5_taxonomy_and_attributes" not in sys.modules:
    ta_stub = types.ModuleType("_5_taxonomy_and_attributes")
    ta_stub.assign_attributes_to_product = lambda *args, **kwargs: None
    sys.modules["_5_taxonomy_and_attributes"] = ta_stub

if "_6_create_variations" not in sys.modules:
    v_stub = types.ModuleType("_6_create_variations")
    v_stub.sync_variations_by_ids = lambda *args, **kwargs: {}
    sys.modules["_6_create_variations"] = v_stub

if "utils" not in sys.modules:
    utils_stub = types.ModuleType("utils")
    utils_stub.normalize_attribute_payload = lambda payload: payload or {}
    utils_stub.parse_subcategory_values = lambda value: [v.strip() for v in str(value).split(",") if v.strip()]
    utils_stub.get_missing_pt_fields = lambda _result: []
    sys.modules["utils"] = utils_stub

if "website_snapshot" not in sys.modules:
    ws_stub = types.ModuleType("website_snapshot")
    ws_stub.compute_website_hash = lambda *_args, **_kwargs: ("", "")
    ws_stub.has_website_changed = lambda *_args, **_kwargs: (False, "")
    ws_stub.send_telegram_notification = lambda *_args, **_kwargs: True
    sys.modules["website_snapshot"] = ws_stub

import main  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RevisedIncompleteGenerationTests(unittest.TestCase):
    @patch.object(main, "sync_variations_by_ids", return_value={})
    @patch.object(main, "assign_attributes_to_product")
    @patch.object(main, "create_product_pt", return_value=202)
    @patch.object(main, "create_product_en", return_value=101)
    @patch.object(main, "compute_website_hash", return_value=("snapshot-hash", "normalized"))
    @patch.object(main, "translate_title_to_en", return_value="Race Name EN")
    @patch.object(main, "extract_text_from_url", return_value=("source text", None))
    @patch.object(main, "build_first_assistant_prompt", return_value="combined source text")
    @patch.object(main, "validate_source_texts", return_value=[])
    @patch.object(main, "generate_image", return_value={"url": "https://example.test/image.png", "id": None})
    @patch.object(main, "call_openai_assistant", return_value={"facts": "ok"})
    @patch.object(
        main,
        "call_second_openai_assistant",
        return_value={
            "summary": "Summary EN",
            "org_info": "Org EN",
            "benefits": ["Benefit 1", "Benefit 2"],
            "faq": "Q: Q1 / A: A1",
            "summary_pt": "Summary PT",
            "org_info_pt": "Org PT",
            "benefits_pt": ["Beneficio 1", "Beneficio 2"],
            "faq_pt": "Q: Q1 / A: A1",
            "image_prompt": "image prompt",
        },
    )
    @patch.object(main, "get_missing_pt_fields", return_value=[])
    @patch.object(main, "get_coordinates_with_city_fallback", return_value=(1.0, 2.0))
    @patch.object(main, "load_config", return_value={"wp_url": "https://example.test", "consumer_key": "ck", "consumer_secret": "cs"})
    @patch.object(main, "log_network_diagnostics")
    @patch.object(main.requests, "get", return_value=_FakeResponse({"slug": "race-slug", "permalink": "https://example.test/event/race-slug"}))
    def test_revised_incomplete_generates_ai_fields(
        self,
        _mock_requests_get,
        _mock_log_network,
        _mock_load_config,
        _mock_geo,
        _mock_missing,
        _mock_second,
        _mock_first,
        _mock_gen_image,
        _mock_validate,
        _mock_build_prompt,
        _mock_extract,
        _mock_translate,
        _mock_hash,
        _mock_create_en,
        _mock_create_pt,
        _mock_assign_attrs,
        _mock_sync_vars,
    ):
        row = {
            "ID": "1",
            "STATUS": "Revised (incomplete)",
            "RACE NAME (PT)": "Corrida Teste",
            "WEBSITE": "https://example.com",
            "REGULATIONS": "",
            "CATEGORY": "Road",
            "SUBCATEGORY": "",
            "ATTRIBUTE": "",
            "VALUE": "",
            "PRICE": "10",
            "LOCATION": "Lisbon",
            "LOCATION (CITY)": "Lisbon",
            "WP PRODUCT ID EN": "",
            "WP PRODUCT ID PT": "",
            "WP VARIATION ID EN": "",
            "WP VARIATION ID PT": "",
        }
        headers = {
            "SUMMARY": 1,
            "ORG INFO": 2,
            "BENEFITS": 3,
            "FAQ": 4,
            "SUMMARY (PT)": 5,
            "ORG INFO (PT)": 6,
            "BENEFITS (PT)": 7,
            "FAQ (PT)": 8,
            "STATUS": 9,
            "IMAGE ID": 10,
        }
        updates = []

        def _capture_update(row_index, values, _headers):
            updates.append((row_index, values.copy()))

        with patch.object(main, "load_all_rows", return_value=([(2, row)], headers)):
            with patch.object(main, "batch_update_cells", side_effect=_capture_update):
                with patch.object(main, "SKIP_AI", False):
                    with patch.object(main, "SKIP_IMAGE", True):
                        main.run_automation()

        ai_update = next((values for _idx, values in updates if "SUMMARY" in values and "FAQ (PT)" in values), None)
        self.assertIsNotNone(ai_update, "Expected AI fields update for Revised (incomplete)")
        self.assertEqual(ai_update.get("SUMMARY"), "Summary EN")
        self.assertEqual(ai_update.get("ORG INFO"), "Org EN")
        self.assertEqual(ai_update.get("SUMMARY (PT)"), "Summary PT")
        self.assertEqual(ai_update.get("FAQ (PT)"), "Q: Q1 / A: A1")

        status_update = next((values for _idx, values in updates if "STATUS" in values), None)
        self.assertIsNotNone(status_update)
        self.assertEqual(status_update.get("STATUS"), main.STATUS_PUBLISHED_INCOMPLETE)


if __name__ == "__main__":
    unittest.main()
