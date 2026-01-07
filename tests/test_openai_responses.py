import json
import os
import sys
import types
import unittest
from tempfile import NamedTemporaryFile

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)


def _seed_env():
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "sheet-id")
    os.environ.setdefault("OPENCAGE_API_KEY", "oc-key")
    os.environ.setdefault("WP_URL", "https://example.com")
    os.environ.setdefault("WP_ADMIN_USER", "admin")
    os.environ.setdefault("WP_ADMIN_PASS", "pass")
    os.environ.setdefault("WP_CONSUMER_KEY", "ck")
    os.environ.setdefault("WP_CONSUMER_SECRET", "cs")


class _DummyResponses:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return types.SimpleNamespace(output_text=json.dumps({"summary": "ok"}))


class _DummyClient:
    def __init__(self):
        self.responses = _DummyResponses()


class OpenAIResponsesTests(unittest.TestCase):
    def setUp(self):
        _seed_env()
        self._install_import_stubs()
        import importlib
        import _2_content_generation as content
        self.content = importlib.reload(content)

    def _install_import_stubs(self):
        import types
        import sys

        if "requests" not in sys.modules:
            sys.modules["requests"] = types.ModuleType("requests")

        if "bs4" not in sys.modules:
            bs4_stub = types.ModuleType("bs4")
            bs4_stub.BeautifulSoup = object
            sys.modules["bs4"] = bs4_stub

        if "PyPDF2" not in sys.modules:
            pypdf_stub = types.ModuleType("PyPDF2")
            pypdf_stub.PdfReader = object
            sys.modules["PyPDF2"] = pypdf_stub

        if "PIL" not in sys.modules:
            pil_stub = types.ModuleType("PIL")
            pil_stub.Image = object
            sys.modules["PIL"] = pil_stub

        if "openai" not in sys.modules:
            openai_stub = types.ModuleType("openai")
            openai_stub.OpenAI = object
            openai_stub.api_key = None
            sys.modules["openai"] = openai_stub

        if "gspread" not in sys.modules:
            sys.modules["gspread"] = types.ModuleType("gspread")

        if "oauth2client" not in sys.modules:
            oauth_stub = types.ModuleType("oauth2client")
            service_account_stub = types.ModuleType("oauth2client.service_account")
            service_account_stub.ServiceAccountCredentials = object
            oauth_stub.service_account = service_account_stub
            sys.modules["oauth2client"] = oauth_stub
            sys.modules["oauth2client.service_account"] = service_account_stub

        if "wordpress_xmlrpc" not in sys.modules:
            wp_stub = types.ModuleType("wordpress_xmlrpc")
            wp_stub.Client = object
            wp_stub.WordPressPost = object
            methods_stub = types.ModuleType("wordpress_xmlrpc.methods")
            methods_stub.media = object
            methods_stub.posts = object
            compat_stub = types.ModuleType("wordpress_xmlrpc.compat")
            compat_stub.xmlrpc_client = object
            sys.modules["wordpress_xmlrpc"] = wp_stub
            sys.modules["wordpress_xmlrpc.methods"] = methods_stub
            sys.modules["wordpress_xmlrpc.compat"] = compat_stub

    def test_load_prompt_file_missing_returns_empty(self):
        value = self.content._load_prompt_file("/missing/prompt.txt")
        self.assertEqual(value, "")

    def test_call_openai_assistant_builds_payload_with_files(self):
        with NamedTemporaryFile("w", delete=False) as system_file:
            system_file.write("SYSTEM")
        self.content.config["openai_text_model"] = "test-model"
        self.content.config["openai_text_reasoning_effort"] = "high"
        self.content.config["openai_text_temperature"] = "0.7"
        self.content.config["openai_system_prompt_file"] = system_file.name

        dummy_client = _DummyClient()
        self.content._OPENAI_CLIENT = dummy_client

        result = self.content.call_openai_assistant("hello", file_ids=["file_1"])
        self.assertEqual(result, {"summary": "ok"})

        kwargs = dummy_client.responses.last_kwargs
        self.assertEqual(kwargs["model"], "test-model")
        self.assertEqual(kwargs["reasoning"]["effort"], "high")
        self.assertEqual(kwargs["temperature"], 0.7)

        payload = kwargs["input"]
        self.assertEqual(payload[0]["role"], "system")
        self.assertEqual(payload[0]["content"][0]["text"], "SYSTEM")
        self.assertEqual(payload[1]["role"], "user")
        content_items = payload[1]["content"]
        self.assertEqual(content_items[0]["type"], "input_text")
        self.assertEqual(content_items[0]["text"], "hello")
        self.assertEqual(content_items[1]["type"], "input_file")
        self.assertEqual(content_items[1]["file_id"], "file_1")

    def test_call_second_openai_assistant_uses_model(self):
        with NamedTemporaryFile("w", delete=False) as system_file:
            system_file.write("SECOND_SYSTEM")
        self.content.config["openai_second_model"] = "second-model"
        self.content.config["openai_second_reasoning_effort"] = "low"
        self.content.config["openai_second_temperature"] = "0.2"
        self.content.config["openai_second_system_prompt_file"] = system_file.name

        dummy_client = _DummyClient()
        self.content._OPENAI_CLIENT = dummy_client

        result = self.content.call_second_openai_assistant({"a": 1})
        self.assertEqual(result, {"summary": "ok"})

        kwargs = dummy_client.responses.last_kwargs
        self.assertEqual(kwargs["model"], "second-model")
        self.assertEqual(kwargs["reasoning"]["effort"], "low")
        self.assertEqual(kwargs["temperature"], 0.2)
        payload = kwargs["input"]
        self.assertEqual(payload[0]["role"], "system")
        self.assertEqual(payload[0]["content"][0]["text"], "SECOND_SYSTEM")
        self.assertEqual(payload[1]["role"], "user")
        self.assertEqual(payload[1]["content"][0]["text"], "{\n  \"a\": 1\n}")

    def test_second_prompt_has_cleanup_rules(self):
        prompt_path = os.path.join(RUN_DIR, "prompts", "second_system.txt")
        with open(prompt_path, "r", encoding="utf-8") as handle:
            prompt_text = handle.read()
        self.assertIn("Также удаляй блоки, где после заголовка нет значения", prompt_text)
        self.assertIn("Также удаляй блоки, где значение — только общий город/страна", prompt_text)
        self.assertIn("удаляй любые блоки, чьи заголовки НЕ входят", prompt_text)
        self.assertIn("Список допустимых заголовков (ТОЛЬКО они разрешены)", prompt_text)
        self.assertIn("строка, состоящая только из \"[]\"", prompt_text)
        self.assertIn("ЖЕСТКО удалить любые строки/блоки, содержащие ссылку на регламент", prompt_text)

    def test_first_prompt_requires_fact_checks(self):
        prompt_path = os.path.join(RUN_DIR, "prompts", "assistant_system.txt")
        with open(prompt_path, "r", encoding="utf-8") as handle:
            prompt_text = handle.read()
        self.assertIn("ПЕРЕД ГЕНЕРАЦИЕЙ:", prompt_text)
        self.assertIn("Если есть противоречия между WEBSITE INFO/REGULATIONS INFO и PDF — приоритет у PDF", prompt_text)
        self.assertIn("Если подтвержденных фактов хватает только на 1 абзац", prompt_text)
        self.assertIn("Если данных по пункту нет — не добавляй этот блок вообще", prompt_text)
        self.assertIn("Секция включает ТОЛЬКО следующие блоки", prompt_text)

    def test_build_first_assistant_prompt_includes_regulations_info(self):
        result = self.content.build_first_assistant_prompt(
            regulations_url="https://example.com/rules",
            regulations_text="Правила регистрации",
            website_text="Описание события"
        )
        self.assertIn("REGULATIONS LINK:\nhttps://example.com/rules", result)
        self.assertIn("REGULATIONS INFO:\nПравила регистрации", result)
        self.assertIn("WEBSITE INFO:\nОписание события", result)

    def test_build_first_assistant_prompt_skips_empty_regulations_info(self):
        result = self.content.build_first_assistant_prompt(
            regulations_url="https://example.com/rules.pdf",
            regulations_text="",
            website_text="Описание события"
        )
        self.assertIn("REGULATIONS LINK:\nhttps://example.com/rules.pdf", result)
        self.assertNotIn("REGULATIONS INFO:", result)
        self.assertIn("WEBSITE INFO:\nОписание события", result)

    def test_validate_source_texts_requires_sources(self):
        errors = self.content.validate_source_texts(
            website_url="https://example.com",
            website_text="",
            regulations_url="https://example.com/rules",
            regulations_text="",
            regulations_pdf_path=None
        )
        self.assertIn("WEBSITE parse failed", errors)
        self.assertIn("REGULATIONS parse failed", errors)

    def test_validate_source_texts_accepts_pdf_regulations(self):
        errors = self.content.validate_source_texts(
            website_url="https://example.com",
            website_text="ok",
            regulations_url="https://example.com/rules.pdf",
            regulations_text="",
            regulations_pdf_path="/tmp/test.pdf"
        )
        self.assertEqual(errors, [])

    def test_extract_text_from_url_retries_with_headers(self):
        class DummyResponse:
            def __init__(self, text):
                self.text = text
                self.headers = {"content-type": "text/html"}

            def raise_for_status(self):
                return None

        class DummyRequests:
            def __init__(self):
                self.calls = []
                self.attempt = 0

            def get(self, url, headers=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "timeout": timeout})
                self.attempt += 1
                if self.attempt < 3:
                    raise Exception("temporary error")
                return DummyResponse("Привет мир")

        sleep_calls = []
        dummy_requests = DummyRequests()
        self.content.requests = dummy_requests
        self.content.time.sleep = lambda seconds: sleep_calls.append(seconds)
        self.content.BeautifulSoup = lambda text, parser: types.SimpleNamespace(
            get_text=lambda separator, strip: text
        )
        self.content.config["fetch_retry_delays_sec"] = "60,120"
        self.content.config["fetch_user_agent"] = "TestAgent/1.0"

        text, pdf_path = self.content.extract_text_from_url("https://example.com/page")
        self.assertEqual(text, "Привет мир")
        self.assertIsNone(pdf_path)
        self.assertEqual(sleep_calls, [60.0, 120.0])
        self.assertEqual(dummy_requests.calls[-1]["headers"]["User-Agent"], "TestAgent/1.0")
        self.assertEqual(dummy_requests.calls[-1]["headers"]["Accept-Language"], "en-US,en;q=0.9,pt-PT;q=0.8,pt;q=0.7")


if __name__ == "__main__":
    unittest.main()
