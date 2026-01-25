import unittest

import os
import sys

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from translation_prompt import build_translation_messages


class TranslationPromptTests(unittest.TestCase):
    def test_translation_prompt_rules(self):
        messages = build_translation_messages("Triatlo de Sao Martinho")
        self.assertEqual(len(messages), 2)
        system_content = messages[0]["content"]
        user_content = messages[1]["content"]
        self.assertIn("Keep proper names", system_content)
        self.assertIn("Translate only generic race terms", system_content)
        self.assertIn("numbers/ordinals", system_content)
        self.assertIn("Keep names unchanged", user_content)
        self.assertIn("2° -> 2nd", user_content)


if __name__ == "__main__":
    unittest.main()
