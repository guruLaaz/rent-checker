#!/usr/bin/env python3
"""Check Gmail for Interac e-Transfer notifications from renters."""

import argparse
import base64
import email
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCRIPT_DIR = Path(__file__).parent
INTERAC_SENDER = "notify@payments.interac.ca"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """Authenticate with OAuth2 and return a Gmail API service."""
    creds = None
    token_path = SCRIPT_DIR / "token.json"
    creds_path = SCRIPT_DIR / "credentials.json"

    if not creds_path.exists():
        print(f"ERROR: No credentials.json found at {creds_path}")
        print("Download OAuth credentials from Google Cloud Console.")
        raise SystemExit(1)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def load_renters():
    """Load renter list from renters.json."""
    renters_path = SCRIPT_DIR / "renters.json"
    if not renters_path.exists():
        print(f"ERROR: No renters.json found at {renters_path}")
        raise SystemExit(1)
    with open(renters_path) as f:
        data = json.load(f)
    return data["renters"]


def get_email_body(payload):
    """Extract the plain-text body from a Gmail API message payload."""
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    # Fallback to text/html
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    # Recurse into nested multipart
    for part in payload.get("parts", []):
        result = get_email_body(part)
        if result:
            return result

    return ""


def parse_transfer_details(subject, body):
    """Extract sender name and amount from an Interac notification email.

    Returns (sender_name, amount) or (None, None) if not parseable.
    """
    text = f"{subject}\n{body}"

    sender_name = None
    amount = None

    # Pattern: "from <NAME>" (e.g. "You've received $360.00 from CHRISTIANE CHALFOUN")
    m = re.search(r"from\s+([\w][\w. -]+?)(?:\s+and\b|\s*,|\s*$)", text, re.IGNORECASE | re.MULTILINE)
    if m:
        sender_name = m.group(1).strip()
        sender_name = re.sub(r"\s*\.\s*$", "", sender_name)

    # Pattern: "<Name> sent you money" (common subject line)
    if not sender_name:
        m = re.search(r"(.+?)\s+sent you money", text, re.IGNORECASE)
        if m:
            sender_name = m.group(1).strip()
            sender_name = re.sub(r"(?i)^(INTERAC e-Transfer:\s*|Re:\s*)", "", sender_name).strip()

    # Pattern: "<Name> sent you $X" or "<Name> a envoy...$X"
    if not sender_name:
        m = re.search(r"(.+?)\s+(?:sent you|a envoy[eé])\s+\$?([\d,]+\.?\d*)", text, re.IGNORECASE)
        if m:
            sender_name = m.group(1).strip()
            sender_name = re.sub(r"(?i)^(INTERAC e-Transfer:\s*|Re:\s*)", "", sender_name).strip()

    # Amount patterns: "$1,200.00" or "1200.00"
    amount_match = re.search(r"\$\s?([\d,]+\.\d{2})", text)
    if amount_match:
        amount = float(amount_match.group(1).replace(",", ""))

    return sender_name, amount


def fetch_interac_emails(service, after_date, before_date=None):
    """Fetch Interac notification emails within a date range using Gmail API."""
    query = f"after:{after_date} label:Transfers-Interac"
    if before_date:
        query += f" before:{before_date}"

    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    transfers = []
    for msg_info in messages:
        msg = service.users().messages().get(userId="me", id=msg_info["id"], format="full").execute()
        payload = msg.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

        subject = headers.get("Subject", "")
        body = get_email_body(payload)
        sender_name, amount = parse_transfer_details(subject, body)

        if sender_name:
            transfers.append({
                "sender": sender_name,
                "amount": amount,
                "date": headers.get("Date", ""),
            })

    return transfers


def check_renters(renters, transfers, label):
    """Match transfers against the renter list and print results."""
    max_name = max((len(r["name"]) for r in renters), default=10)
    max_name = max(max_name, 6)

    print(f"\n  Rent Transfers ({label})")
    print(f"  {'─' * (max_name + 28)}")

    all_received = True
    for renter in renters:
        name = renter["name"]
        expected = renter.get("expected_amount")

        def normalize(s):
            return s.lower().replace("-", " ")

        matched = [
            t for t in transfers
            if normalize(name) in normalize(t["sender"])
            or normalize(t["sender"]) in normalize(name)
        ]

        if matched:
            transfer = matched[-1]
            actual = transfer.get("amount")
            if expected and actual:
                amount_str = f"${actual:,.2f}"
                if abs(actual - expected) > 0.01:
                    status = f"YES (expected ${expected:,.2f})"
                else:
                    status = "YES"
            else:
                amount_str = f"${actual:,.2f}" if actual else "  -  "
                status = "YES"
        else:
            amount_str = "  -  "
            status = "NO"
            all_received = False

        print(f"  {name:<{max_name}}  {amount_str:>12}   {status}")

    print()
    if all_received:
        print("  All transfers received.")
    else:
        print("  Some transfers are MISSING.")
    print()


def main():
    parser = argparse.ArgumentParser(description="Check Interac e-Transfers from renters")
    parser.add_argument("--days", type=int, default=5, help="Number of days to look back (default: 5)")
    parser.add_argument("--after", type=str, help="Start date (YYYY/MM/DD)")
    parser.add_argument("--before", type=str, help="End date (YYYY/MM/DD)")
    args = parser.parse_args()

    if args.after:
        after_date = args.after
        label = f"{after_date} to {args.before or 'now'}"
    else:
        after_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y/%m/%d")
        label = f"last {args.days} days"

    print("\nConnecting to Gmail...")
    service = get_gmail_service()
    transfers = fetch_interac_emails(service, after_date, args.before)
    print(f"Found {len(transfers)} Interac transfer(s) ({label}).")

    renters = load_renters()
    check_renters(renters, transfers, label)


if __name__ == "__main__":
    main()
