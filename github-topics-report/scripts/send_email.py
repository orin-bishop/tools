"""Send out/email.html over SMTP. Fallback for when the Harness email template isn't used.

Environment:
  EMAIL_RECIPIENTS  comma-separated list (required)
  EMAIL_FROM        sender address (required)
  SMTP_HOST         required;  SMTP_PORT default 587 (STARTTLS unless port is 25)
  SMTP_USER / SMTP_PASSWORD   optional login
  OUT_DIR           default "out" (reads email.html and email_subject.txt)
"""
from __future__ import annotations

import os
import re
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)</(p|h\d|tr|li|table)>", "\n", text)
    text = re.sub(r"(?i)</t[dh]>", " | ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def build_message(html: str, subject: str, sender: str, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(html_to_text(html))
    msg.add_alternative(html, subtype="html")
    return msg


def main() -> int:
    out = Path(os.environ.get("OUT_DIR", "out"))
    recipients = [r.strip() for r in os.environ["EMAIL_RECIPIENTS"].split(",") if r.strip()]
    if not recipients:
        sys.exit("EMAIL_RECIPIENTS is empty")
    msg = build_message(
        (out / "email.html").read_text(encoding="utf-8"),
        (out / "email_subject.txt").read_text(encoding="utf-8").strip(),
        os.environ["EMAIL_FROM"],
        recipients,
    )
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=60) as smtp:
        if port != 25:
            smtp.starttls()
        if os.environ.get("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)
    print(f"Sent '{msg['Subject']}' to {len(recipients)} recipient(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
