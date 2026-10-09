"""Create source excerpts for a human review of confirmed contact candidates.

This tool is read-only. It consumes one or more backfill CSV reports and fetches
only the sources for rows that were eligible for automatic updates.
"""

import argparse
import csv
import glob
import re
from pathlib import Path

from PyPDF2 import PdfReader

from _2_content_generation import extract_text_from_url
from url_utils import unwrap_google_viewer_url


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or " ").strip()


def _excerpt(text: str, email: str, radius: int = 220) -> str:
    """Return a small readable source excerpt around a literal email address."""
    normalized = _compact(text)
    if not normalized:
        return ""
    match = re.search(re.escape(email), normalized, flags=re.IGNORECASE)
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(normalized), match.end() + radius)
    prefix = "…" if start else ""
    suffix = "…" if end < len(normalized) else ""
    return prefix + normalized[start:end] + suffix


def _pdf_text(path: str | None) -> str:
    if not path:
        return ""
    try:
        with open(path, "rb") as source:
            return "\n".join(page.extract_text() or "" for page in PdfReader(source).pages)
    except Exception:
        return ""


def _excerpts(text: str, emails: str) -> str:
    return "\n---\n".join(
        excerpt for email in emails.split(",")
        if (excerpt := _excerpt(text, email.strip()))
    )


def _head(text: str, length: int = 500) -> str:
    return _compact(text)[:length]


def _confirmed_rows(pattern: str) -> list[dict]:
    rows = []
    for filename in sorted(glob.glob(pattern)):
        with open(filename, encoding="utf-8", newline="") as source:
            rows.extend(row for row in csv.DictReader(source) if row.get("updated_fields"))
    return rows


def audit(pattern: str, report: str) -> None:
    fields = [
        "id", "race", "proposed_name", "proposed_email", "website", "regulations",
        "website_head", "regulations_head", "pdf_head",
        "website_excerpt", "regulations_excerpt", "pdf_excerpt", "manual_verdict",
    ]
    audited = []
    for row in _confirmed_rows(pattern):
        website_url = row.get("website", "").strip()
        regulations_url = unwrap_google_viewer_url(row.get("regulations", "").strip())
        website_text, _ = extract_text_from_url(website_url) if website_url else ("", None)
        regulations_text, pdf_path = (
            extract_text_from_url(regulations_url) if regulations_url else ("", None)
        )
        emails = row.get("proposed_email", "")
        pdf_text = _pdf_text(pdf_path)
        audited.append({
            "id": row.get("id", ""),
            "race": row.get("race", ""),
            "proposed_name": row.get("proposed_name", ""),
            "proposed_email": row.get("proposed_email", ""),
            "website": website_url,
            "regulations": regulations_url,
            "website_head": _head(website_text),
            "regulations_head": _head(regulations_text),
            "pdf_head": _head(pdf_text),
            "website_excerpt": _excerpts(website_text, emails),
            "regulations_excerpt": _excerpts(regulations_text, emails),
            "pdf_excerpt": _excerpts(pdf_text, emails),
            "manual_verdict": "",
        })

    output = Path(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audited)
    print(f"Audited {len(audited)} confirmed candidate(s): {output}")


def parse_args():
    parser = argparse.ArgumentParser(description="Read-only organizer-contact source audit")
    parser.add_argument("--input", default="/app/logs/organizer_contacts_sample50_part*.csv")
    parser.add_argument("--report", default="/app/logs/organizer_contacts_sample50_manual_audit.csv")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    audit(args.input, args.report)
