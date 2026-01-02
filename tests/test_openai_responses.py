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
        self.content.config["openai_system_prompt_file"] = system_file.name

        dummy_client = _DummyClient()
        self.content._OPENAI_CLIENT = dummy_client

        result = self.content.call_openai_assistant("hello", file_ids=["file_1"])
        self.assertEqual(result, {"summary": "ok"})

        kwargs = dummy_client.responses.last_kwargs
        self.assertEqual(kwargs["model"], "test-model")
        self.assertEqual(kwargs["reasoning"]["effort"], "high")

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
        self.content.config["openai_second_system_prompt_file"] = system_file.name

        dummy_client = _DummyClient()
        self.content._OPENAI_CLIENT = dummy_client

        result = self.content.call_second_openai_assistant({"a": 1})
        self.assertEqual(result, {"summary": "ok"})

        kwargs = dummy_client.responses.last_kwargs
        self.assertEqual(kwargs["model"], "second-model")
        self.assertEqual(kwargs["reasoning"]["effort"], "low")
        payload = kwargs["input"]
        self.assertEqual(payload[0]["role"], "system")
        self.assertEqual(payload[0]["content"][0]["text"], "SECOND_SYSTEM")
        self.assertEqual(payload[1]["role"], "user")
        self.assertEqual(payload[1]["content"][0]["text"], "{\n  \"a\": 1\n}")


if __name__ == "__main__":
    unittest.main()
