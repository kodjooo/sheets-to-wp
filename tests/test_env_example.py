import os
import unittest


class EnvExampleTests(unittest.TestCase):
    def test_env_example_contains_required_keys(self):
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env.example")
        with open(env_path, "r", encoding="utf-8") as env_file:
            lines = env_file.read().splitlines()

        keys = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                keys.append(stripped.split("=", 1)[0].strip())

        required = {
            "OPENAI_API_KEY",
            "OPENAI_TEXT_MODEL",
            "OPENAI_SECOND_MODEL",
            "OPENAI_TEXT_REASONING_EFFORT",
            "OPENAI_SECOND_REASONING_EFFORT",
            "OPENAI_TEXT_TEMPERATURE",
            "OPENAI_SECOND_TEMPERATURE",
            "OPENAI_SYSTEM_PROMPT_FILE",
            "OPENAI_SECOND_SYSTEM_PROMPT_FILE",
            "OPENCAGE_API_KEY",
            "GOOGLE_SPREADSHEET_ID",
            "GOOGLE_WORKSHEET_NAME",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_SERVICE_ACCOUNT_JSON",
            "GOOGLE_SHEETS_CACHE_TTL_SEC",
            "GOOGLE_SHEETS_UPDATE_MAX_ATTEMPTS",
            "GOOGLE_SHEETS_UPDATE_BASE_DELAY_SEC",
            "WP_URL",
            "WP_ADMIN_USER",
            "WP_ADMIN_PASS",
            "WP_CONSUMER_KEY",
            "WP_CONSUMER_SECRET",
            "SKIP_AI",
            "SKIP_IMAGE",
            "SLEEP_SECONDS",
            "RUN_ON_STARTUP",
            "SCHEDULED_HOUR",
            "SCHEDULED_MINUTE",
            "TIMEZONE",
            "WCAPI_MAX_ATTEMPTS",
            "WCAPI_BASE_DELAY_SEC",
            "WCAPI_TIMEOUT_SEC",
            "LOG_LEVEL",
            "HTTP_FETCH_USER_AGENT",
            "HTTP_FETCH_RETRY_DELAYS_SEC",
        }

        missing = [key for key in sorted(required) if key not in keys]
        self.assertFalse(missing, f"Нет ключей в .env.example: {', '.join(missing)}")


if __name__ == "__main__":
    unittest.main()
