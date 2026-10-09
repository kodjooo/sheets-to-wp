"""Backfill missing organizer contacts without invoking the publishing pipeline.

The script reads only main event rows with an empty ORGANIZER EMAIL.  It fetches
their existing WEBSITE and REGULATIONS sources, asks OpenAI only for verified
organizer contacts, and writes only missing contact cells in --mode apply.
"""

import argparse
import csv
import logging
import os
import re
import unicodedata
from pathlib import Path

import openai
from PyPDF2 import PdfReader

from _1_google_loader import load_all_rows, update_only_blank_cells
from _2_content_generation import (
    build_first_assistant_prompt,
    call_organizer_contacts_assistant,
    extract_text_from_url,
)
from url_utils import unwrap_google_viewer_url


EMAIL_RE = re.compile(r"[^@\s,;<>()]+@[^@\s,;<>()]+\.[^@\s,;<>()]+")

# Common event-type words do not identify one particular race.  Requiring a
# remaining title token prevents a contact found only in an unrelated linked
# regulation (for example, a different race hosted on the same platform) from
# being written automatically.
EVENT_TITLE_STOP_WORDS = {
    "a", "ao", "as", "da", "das", "de", "do", "dos", "e", "em", "o", "os",
    "the", "and", "for", "with", "corrida", "caminhada", "trail", "trilho",
    "passeio", "prova", "evento", "edicao", "edicao", "taca", "campeonato",
    "campeonatos", "maratona", "meia", "nacional", "regionais", "regional",
}

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def _clean(value) -> str:
    return str(value or "").strip()


def extract_valid_emails(raw: str) -> str:
    """Normalize, validate and deduplicate AI-proposed email addresses."""
    seen, emails = set(), []
    for match in EMAIL_RE.findall(_clean(raw)):
        email = match.strip().lower().rstrip(".")
        # Some PDFs lose the separator after a label such as "e-mail:" and
        # return `paraoemailcontact@domain.pt` as one token. Recover the
        # literal address after the last label; no email or domain is invented.
        local, separator, domain = email.rpartition("@")
        for label in ("e-mail", "email"):
            if label in local:
                suffix = local.rsplit(label, 1)[1]
                if suffix:
                    email = f"{suffix}{separator}{domain}"
                break
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    return ", ".join(emails)


def _email_list(raw: str) -> list[str]:
    normalized = extract_valid_emails(raw)
    return [email.strip() for email in normalized.split(",") if email.strip()]


def event_identity_tokens(race_name: str) -> set[str]:
    """Return distinctive, normalized title tokens suitable for source checks."""
    normalized = unicodedata.normalize("NFKD", _clean(race_name)).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", normalized.lower())
    return {
        word for word in words
        if len(word) >= 4 and not word.isdigit() and word not in EVENT_TITLE_STOP_WORDS
    }


def source_matches_event(race_name: str, source_text: str) -> bool:
    """Whether a particular source itself names this event.

    This deliberately requires a distinctive event-name token. A missing match
    is a manual-review case rather than an error or a reason to guess.
    """
    tokens = event_identity_tokens(race_name)
    if not tokens:
        return False
    normalized_source = unicodedata.normalize("NFKD", _clean(source_text)).encode(
        "ascii", "ignore"
    ).decode().lower()
    source_words = set(re.findall(r"[a-z0-9]+", normalized_source))
    return bool(tokens.intersection(source_words))


def event_matched_source_emails(
    race_name: str, website_text: str, regulations_text: str, pdf_path: str | None
) -> str:
    """Literal emails only from individual sources that identify the same event."""
    sources = [website_text or "", regulations_text or ""]
    if pdf_path:
        try:
            with open(pdf_path, "rb") as pdf_file:
                sources.append("\n".join(page.extract_text() or "" for page in PdfReader(pdf_file).pages))
        except Exception as exc:
            logging.warning("Could not extract PDF text for event-match audit: %s", exc)
    return extract_valid_emails("\n".join(
        source for source in sources if source_matches_event(race_name, source)
    ))


def extract_source_emails(website_text: str, regulations_text: str, pdf_path: str | None) -> str:
    """Extract every literal email from the supplied sources for review.

    This is an audit signal, not a claim that every address belongs to the
    organizer. It lets reviewers spot cases where the AI did not select an
    email that is visibly present in a source.
    """
    text_parts = [website_text or "", regulations_text or ""]
    if pdf_path:
        try:
            with open(pdf_path, "rb") as pdf_file:
                text_parts.extend((page.extract_text() or "") for page in PdfReader(pdf_file).pages)
        except Exception as exc:
            logging.warning("Could not extract PDF text for email audit: %s", exc)
    return extract_valid_emails("\n".join(text_parts))


def is_candidate_row(row: dict) -> bool:
    """Only event main rows with an unfilled organizer-email field are eligible."""
    return bool(_clean(row.get("ID"))) and not _clean(row.get("ORGANIZER EMAIL"))


def build_updates(row: dict, result: dict | None) -> dict:
    """Return the smallest safe update set. Existing values are never replaced."""
    if not isinstance(result, dict):
        return {}
    email = extract_valid_emails(result.get("organizer_email", ""))
    if not email:
        return {}

    updates = {}
    if not _clean(row.get("ORGANIZER EMAIL")):
        updates["ORGANIZER EMAIL"] = email
    name = _clean(result.get("organizer_name"))
    if name and not _clean(row.get("ORGANIZER NAME")):
        updates["ORGANIZER NAME"] = name
    return updates


def collect_sources(row: dict):
    """Fetch sources sequentially; a usable website or regulation is sufficient."""
    website_url = _clean(row.get("WEBSITE"))
    regulations_url = unwrap_google_viewer_url(_clean(row.get("REGULATIONS")))
    website_text, _ = extract_text_from_url(website_url) if website_url else ("", None)
    regulations_text, pdf_path = (
        extract_text_from_url(regulations_url) if regulations_url else ("", None)
    )
    return website_url, website_text, regulations_url, regulations_text, pdf_path


def upload_pdf(pdf_path: str | None) -> list[str]:
    if not pdf_path:
        return []
    with open(pdf_path, "rb") as source:
        response = openai.files.create(file=source, purpose="assistants")
    return [response.id]


def write_report(path: str, rows: list[dict]) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "row", "id", "race", "status", "website", "regulations",
        "source_emails", "event_matched_emails", "proposed_name", "proposed_email", "updated_fields", "note",
    ]
    with report_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def apply_saved_report(path: str) -> dict:
    """Apply only accepted rows from a previous dry-run report.

    This intentionally makes no web or OpenAI calls. Rows are located again by
    event ID, and the regular write helper still writes only blank cells.
    """
    with open(path, encoding="utf-8-sig", newline="") as report_file:
        report_rows = list(csv.DictReader(report_file))

    rows, headers = load_all_rows()
    required_headers = {"ID", "ORGANIZER NAME", "ORGANIZER EMAIL"}
    missing_headers = sorted(required_headers.difference(headers))
    if missing_headers:
        raise ValueError("Missing required columns: " + ", ".join(missing_headers))

    rows_by_id: dict[str, tuple[int, dict] | None] = {}
    for row_index, row in rows:
        event_id = _clean(row.get("ID"))
        if not event_id:
            continue
        rows_by_id[event_id] = (row_index, row) if event_id not in rows_by_id else None

    summary = {"accepted": 0, "written": 0, "skipped": 0}
    for report_row in report_rows:
        event_id = _clean(report_row.get("id"))
        # Only a successful dry-run candidate has update fields and no review
        # note. A hand-edited or incomplete report therefore cannot add rows.
        if not _clean(report_row.get("updated_fields")) or _clean(report_row.get("note")):
            continue
        target = rows_by_id.get(event_id)
        proposed_email = extract_valid_emails(report_row.get("proposed_email", ""))
        if not target or not proposed_email:
            summary["skipped"] += 1
            continue
        row_index, row = target
        updates = {"ORGANIZER EMAIL": proposed_email}
        proposed_name = _clean(report_row.get("proposed_name"))
        if proposed_name:
            updates["ORGANIZER NAME"] = proposed_name
        summary["accepted"] += 1
        written = update_only_blank_cells(row_index, updates, headers)
        summary["written"] += bool(written)
        if not written:
            summary["skipped"] += 1
    logging.info("Contacts backfill apply saved report: %s", summary)
    return summary


def run(mode: str, limit: int = 0, only_ids: set[str] | None = None, report: str = "") -> dict:
    if mode not in {"dry-run", "apply"}:
        raise ValueError("mode must be 'dry-run' or 'apply'")

    rows, headers = load_all_rows()
    required_headers = {"ID", "ORGANIZER NAME", "ORGANIZER EMAIL", "WEBSITE", "REGULATIONS"}
    missing_headers = sorted(required_headers.difference(headers))
    if missing_headers:
        raise ValueError("Missing required columns: " + ", ".join(missing_headers))

    selected = [
        (row_index, row) for row_index, row in rows
        if is_candidate_row(row) and (not only_ids or _clean(row.get("ID")) in only_ids)
    ]
    if limit:
        selected = selected[:limit]

    report_rows = []
    summary = {"selected": len(selected), "proposed": 0, "written": 0, "skipped": 0}
    for row_index, row in selected:
        event_id = _clean(row.get("ID"))
        entry = {
            "row": row_index,
            "id": event_id,
            "race": _clean(row.get("RACE NAME (PT)")) or _clean(row.get("RACE NAME")),
            "status": _clean(row.get("STATUS")),
            "website": _clean(row.get("WEBSITE")),
            "regulations": _clean(row.get("REGULATIONS")),
            "source_emails": "",
            "event_matched_emails": "",
            "proposed_name": "",
            "proposed_email": "",
            "updated_fields": "",
            "note": "",
        }
        try:
            website_url, website_text, regulations_url, regulations_text, pdf_path = collect_sources(row)
            if not website_text and not regulations_text and not pdf_path:
                entry["note"] = "No readable website or regulations source"
                summary["skipped"] += 1
                report_rows.append(entry)
                continue

            source_text = build_first_assistant_prompt(regulations_url, regulations_text, website_text)
            entry["source_emails"] = extract_source_emails(
                website_text, regulations_text, pdf_path
            )
            entry["event_matched_emails"] = event_matched_source_emails(
                entry["race"], website_text, regulations_text, pdf_path
            )
            source_text = (
                f"EVENT ID: {event_id}\n"
                f"EVENT NAME: {entry['race']}\n\n"
                f"{source_text}"
            )
            result = call_organizer_contacts_assistant(source_text, file_ids=upload_pdf(pdf_path))
            updates = build_updates(row, result)
            entry["proposed_name"] = _clean((result or {}).get("organizer_name"))
            entry["proposed_email"] = extract_valid_emails((result or {}).get("organizer_email", ""))
            if not updates:
                if entry["source_emails"]:
                    entry["note"] = "Review: source email found but AI did not select an organizer email"
                else:
                    entry["note"] = "No verified organizer email returned"
                summary["skipped"] += 1
                report_rows.append(entry)
                continue

            source_emails = set(_email_list(entry["source_emails"]))
            proposed_emails = set(_email_list(entry["proposed_email"]))
            if not proposed_emails.issubset(source_emails):
                entry["note"] = "Review: AI email was not found by literal source-email scan"
                entry["updated_fields"] = ""
                summary["skipped"] += 1
                report_rows.append(entry)
                continue

            event_matched_emails = set(_email_list(entry["event_matched_emails"]))
            if not proposed_emails.issubset(event_matched_emails):
                entry["note"] = "Review: email was not found in a source that identifies this event"
                entry["updated_fields"] = ""
                summary["skipped"] += 1
                report_rows.append(entry)
                continue

            summary["proposed"] += 1
            entry["updated_fields"] = ", ".join(sorted(updates))
            if mode == "apply":
                # Re-check the cells immediately before writing. This preserves a
                # contact added manually while the backfill was running.
                written = update_only_blank_cells(row_index, updates, headers)
                entry["updated_fields"] = ", ".join(sorted(written))
                summary["written"] += bool(written)
                if not written:
                    entry["note"] = "Skipped: contact field was filled during run"
            report_rows.append(entry)
        except Exception as exc:  # Continue with remaining independent events.
            logging.exception("Contacts backfill failed for event ID=%s", event_id)
            entry["note"] = f"Error: {exc}"
            summary["skipped"] += 1
            report_rows.append(entry)

    if report:
        write_report(report, report_rows)
    logging.info("Contacts backfill %s: %s", mode, summary)
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill missing organizer contacts only")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--limit", type=int, default=0, help="Max events to inspect; 0 means all")
    parser.add_argument("--id", dest="ids", action="append", default=[], help="Process one event ID; repeatable")
    parser.add_argument("--report", default="", help="Optional CSV report path")
    parser.add_argument(
        "--apply-report", default="",
        help="Apply accepted rows from an existing dry-run CSV; makes no OpenAI calls",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.apply_report:
        apply_saved_report(args.apply_report)
    else:
        run(args.mode, limit=args.limit, only_ids=set(args.ids), report=args.report)
