import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch


RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")


def _load_backfill_module():
    loader_stub = types.ModuleType("_1_google_loader")
    loader_stub.load_all_rows = lambda: ([], [])
    loader_stub.update_only_blank_cells = lambda *_args: {}
    content_stub = types.ModuleType("_2_content_generation")
    content_stub.build_first_assistant_prompt = lambda *_args: "source"
    content_stub.call_organizer_contacts_assistant = lambda *_args, **_kwargs: {}
    content_stub.extract_text_from_url = lambda *_args: ("", None)
    url_stub = types.ModuleType("url_utils")
    url_stub.unwrap_google_viewer_url = lambda value: value
    openai_stub = types.ModuleType("openai")
    openai_stub.files = types.SimpleNamespace(create=lambda **_kwargs: None)
    pypdf_stub = types.ModuleType("PyPDF2")
    pypdf_stub.PdfReader = object

    replacements = {
        "_1_google_loader": loader_stub,
        "_2_content_generation": content_stub,
        "url_utils": url_stub,
        "openai": openai_stub,
        "PyPDF2": pypdf_stub,
    }
    original = {key: sys.modules.get(key) for key in replacements}
    sys.modules.update(replacements)
    try:
        spec = importlib.util.spec_from_file_location(
            "backfill_organizer_contacts_test", os.path.join(RUN_DIR, "backfill_organizer_contacts.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, previous in original.items():
            if previous is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = previous


contacts = _load_backfill_module()


class OrganizerContactsBackfillTests(unittest.TestCase):
    def test_email_scan_repairs_pdf_label_concatenation(self):
        self.assertEqual(
            contacts.extract_valid_emails("Para o emailmr3eventus@gmail.com para informações"),
            "mr3eventus@gmail.com",
        )

    def test_only_main_rows_with_blank_email_are_candidates(self):
        self.assertTrue(contacts.is_candidate_row({"ID": "42", "ORGANIZER EMAIL": ""}))
        self.assertFalse(contacts.is_candidate_row({"ID": "", "ORGANIZER EMAIL": ""}))
        self.assertFalse(contacts.is_candidate_row({"ID": "42", "ORGANIZER EMAIL": "info@example.pt"}))

    def test_build_updates_validates_email_and_preserves_existing_values(self):
        result = {"organizer_name": "Race Org", "organizer_email": "Info@Race.pt, invalid"}
        self.assertEqual(
            contacts.build_updates({"ORGANIZER NAME": "", "ORGANIZER EMAIL": ""}, result),
            {"ORGANIZER EMAIL": "info@race.pt", "ORGANIZER NAME": "Race Org"},
        )
        self.assertEqual(
            contacts.build_updates(
                {"ORGANIZER NAME": "Manual name", "ORGANIZER EMAIL": "manual@example.pt"}, result
            ),
            {},
        )
        self.assertEqual(
            contacts.build_updates({"ORGANIZER NAME": "", "ORGANIZER EMAIL": ""}, {"organizer_email": "not an email"}),
            {},
        )

    def test_source_email_scan_deduplicates_literal_addresses(self):
        self.assertEqual(
            contacts.extract_source_emails(
                "Contact INFO@Race.pt", "Email: info@race.pt; team@example.org", None
            ),
            "info@race.pt, team@example.org",
        )

    def test_dry_run_never_writes_and_reports_proposal(self):
        row = {
            "ID": "42", "STATUS": "Published", "RACE NAME (PT)": "Corrida",
            "ORGANIZER NAME": "", "ORGANIZER EMAIL": "",
            "WEBSITE": "https://example.test", "REGULATIONS": "",
        }
        report_rows = []
        with patch.object(contacts, "load_all_rows", return_value=([(2, row)], list(row))):
            with patch.object(
                contacts, "collect_sources",
                return_value=("https://example.test", "website source info@race.pt", "", "", None),
            ):
                with patch.object(
                    contacts, "call_organizer_contacts_assistant",
                    return_value={"organizer_name": "Race Org", "organizer_email": "info@race.pt"},
                ):
                    with patch.object(contacts, "update_only_blank_cells") as write:
                        with patch.object(contacts, "write_report", side_effect=lambda _path, rows: report_rows.extend(rows)):
                            summary = contacts.run("dry-run", report="report.csv")

        self.assertEqual(summary, {"selected": 1, "proposed": 1, "written": 0, "skipped": 0})
        write.assert_not_called()
        self.assertEqual(report_rows[0]["proposed_email"], "info@race.pt")

    def test_unconfirmed_ai_email_is_marked_for_review(self):
        row = {
            "ID": "43", "STATUS": "Published", "RACE NAME (PT)": "Corrida",
            "ORGANIZER NAME": "", "ORGANIZER EMAIL": "",
            "WEBSITE": "https://example.test", "REGULATIONS": "",
        }
        report_rows = []
        with patch.object(contacts, "load_all_rows", return_value=([(2, row)], list(row))):
            with patch.object(
                contacts, "collect_sources",
                return_value=("https://example.test", "website source", "", "", None),
            ):
                with patch.object(
                    contacts, "call_organizer_contacts_assistant",
                    return_value={"organizer_name": "Race Org", "organizer_email": "info@race.pt"},
                ):
                    with patch.object(contacts, "update_only_blank_cells") as write:
                        with patch.object(contacts, "write_report", side_effect=lambda _path, rows: report_rows.extend(rows)):
                            summary = contacts.run("apply", report="report.csv")

        self.assertEqual(summary, {"selected": 1, "proposed": 0, "written": 0, "skipped": 1})
        write.assert_not_called()
        self.assertIn("Review", report_rows[0]["note"])


if __name__ == "__main__":
    unittest.main()
