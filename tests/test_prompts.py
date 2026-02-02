import os
import unittest


class PromptTests(unittest.TestCase):
    def test_assistant_system_has_faq_keys(self):
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "run", "prompts", "assistant_system.txt"
        )
        with open(prompt_path, "r", encoding="utf-8") as prompt_file:
            content = prompt_file.read()
        self.assertIn("faq", content)
        self.assertIn("faq_pt", content)

    def test_second_system_includes_faq_fields(self):
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "run", "prompts", "second_system.txt"
        )
        with open(prompt_path, "r", encoding="utf-8") as prompt_file:
            content = prompt_file.read()
        self.assertIn("\"faq\":", content)
        self.assertIn("\"faq_pt\":", content)


if __name__ == "__main__":
    unittest.main()
