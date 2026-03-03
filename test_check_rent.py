"""Tests for check_rent.py"""

import base64
from io import StringIO
from unittest.mock import MagicMock

import pytest

from check_rent import check_renters, fetch_interac_emails, get_email_body, parse_transfer_details, INTERAC_SENDER


# --- parse_transfer_details ---


class TestParseFromPattern:
    """Emails with 'You've received $X from NAME' format."""

    def test_all_caps_name(self):
        subject = "Interac e-Transfer: You've received $360.00 from CHRISTIANE CHALFOUN and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, "")
        assert name == "CHRISTIANE CHALFOUN"
        assert amount == 360.00

    def test_mixed_case_name(self):
        subject = "Interac e-Transfer: You've received $535.00 from Real Labelle and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, "")
        assert name == "Real Labelle"
        assert amount == 535.00

    def test_hyphenated_name(self):
        subject = "Interac e-Transfer: You've received $860.00 from ANNIE-CLAUDE DAVID and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, "")
        assert name == "ANNIE-CLAUDE DAVID"
        assert amount == 860.00

    def test_long_org_name(self):
        subject = "Interac e-Transfer: You've received $320.00 from MATRIX SERVICES DE READAPTATION INC and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, "")
        assert name == "MATRIX SERVICES DE READAPTATION INC"
        assert amount == 320.00

    def test_name_with_period(self):
        subject = "Interac e-Transfer: You've received $370.00 from RESILIENCE PSYCHOTHERAPY LTD. and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, "")
        assert "RESILIENCE PSYCHOTHERAPY" in name
        assert amount == 370.00

    def test_large_amount_with_comma(self):
        subject = "Interac e-Transfer: You've received $1,020.00 from CAMILLO ZACCHIA and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, "")
        assert name == "CAMILLO ZACCHIA"
        assert amount == 1020.00


class TestParseSentYouPattern:
    """Emails with 'NAME sent you money' format."""

    def test_sent_you_money_subject(self):
        subject = "INTERAC e-Transfer: John Smith sent you money"
        name, amount = parse_transfer_details(subject, "")
        assert name == "John Smith"

    def test_sent_you_amount(self):
        subject = ""
        body = "Jane Doe sent you $950.00"
        name, amount = parse_transfer_details(subject, body)
        assert name == "Jane Doe"
        assert amount == 950.00


class TestParseFromBody:
    """Name extracted from body text."""

    def test_from_name_in_body(self):
        subject = ""
        body = "You've received $500.00 from John Smith and it has been automatically deposited."
        name, amount = parse_transfer_details(subject, body)
        assert "John Smith" in name
        assert amount == 500.00


class TestParseEdgeCases:
    def test_no_match_returns_none(self):
        name, amount = parse_transfer_details("Hello world", "No transfer info here")
        assert name is None
        assert amount is None

    def test_amount_without_name(self):
        name, amount = parse_transfer_details("", "You got $100.00")
        assert amount == 100.00

    def test_empty_strings(self):
        name, amount = parse_transfer_details("", "")
        assert name is None
        assert amount is None


# --- get_email_body ---


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


class TestGetEmailBody:
    def test_simple_body(self):
        payload = {"body": {"data": _b64("Hello world")}}
        assert get_email_body(payload) == "Hello world"

    def test_multipart_plain_text(self):
        payload = {
            "body": {},
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Plain text body")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML body</p>")}},
            ],
        }
        assert get_email_body(payload) == "Plain text body"

    def test_multipart_html_fallback(self):
        payload = {
            "body": {},
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML only</p>")}},
            ],
        }
        assert get_email_body(payload) == "<p>HTML only</p>"

    def test_nested_multipart(self):
        payload = {
            "body": {},
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Nested plain")}},
                    ],
                },
            ],
        }
        assert get_email_body(payload) == "Nested plain"

    def test_empty_payload(self):
        assert get_email_body({}) == ""
        assert get_email_body({"body": {}}) == ""


# --- check_renters ---


class TestCheckRenters:
    def test_all_received(self, capsys):
        renters = [
            {"name": "John Smith", "expected_amount": 500.00},
            {"name": "Jane Doe", "expected_amount": 800.00},
        ]
        transfers = [
            {"sender": "JOHN SMITH", "amount": 500.00, "date": ""},
            {"sender": "JANE DOE", "amount": 800.00, "date": ""},
        ]
        check_renters(renters, transfers, "last 5 days")
        output = capsys.readouterr().out
        assert "All transfers received" in output
        assert "YES" in output

    def test_missing_transfer(self, capsys):
        renters = [
            {"name": "John Smith", "expected_amount": 500.00},
            {"name": "Jane Doe", "expected_amount": 800.00},
        ]
        transfers = [
            {"sender": "JOHN SMITH", "amount": 500.00, "date": ""},
        ]
        check_renters(renters, transfers, "last 5 days")
        output = capsys.readouterr().out
        assert "MISSING" in output
        assert "NO" in output

    def test_amount_mismatch(self, capsys):
        renters = [{"name": "John Smith", "expected_amount": 500.00}]
        transfers = [{"sender": "JOHN SMITH", "amount": 450.00, "date": ""}]
        check_renters(renters, transfers, "last 5 days")
        output = capsys.readouterr().out
        assert "expected $500.00" in output

    def test_hyphen_vs_space_matching(self, capsys):
        renters = [{"name": "Annie Claude David", "expected_amount": 860.00}]
        transfers = [{"sender": "ANNIE-CLAUDE DAVID", "amount": 860.00, "date": ""}]
        check_renters(renters, transfers, "last 5 days")
        output = capsys.readouterr().out
        assert "YES" in output
        assert "MISSING" not in output

    def test_partial_name_match(self, capsys):
        renters = [{"name": "Dre Nadia", "expected_amount": 60.00}]
        transfers = [{"sender": "ACADEMIE DRE NADIA GAGNIER", "amount": 60.00, "date": ""}]
        check_renters(renters, transfers, "last 5 days")
        output = capsys.readouterr().out
        assert "YES" in output

    def test_no_expected_amount(self, capsys):
        renters = [{"name": "John Smith"}]
        transfers = [{"sender": "JOHN SMITH", "amount": 999.00, "date": ""}]
        check_renters(renters, transfers, "last 5 days")
        output = capsys.readouterr().out
        assert "YES" in output


# --- fetch_interac_emails ---


def _make_gmail_message(msg_id, from_addr, subject, body_text):
    """Build a mock Gmail API message response."""
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Mon, 1 Mar 2026 10:00:00 -0500"},
            ],
            "body": {"data": base64.urlsafe_b64encode(body_text.encode()).decode()},
        },
    }


def _mock_service(messages):
    """Create a mock Gmail API service that returns the given messages."""
    service = MagicMock()
    msg_list = [{"id": m["id"]} for m in messages]
    service.users().messages().list().execute.return_value = {"messages": msg_list}

    def get_side_effect(userId, id, format):
        for m in messages:
            if m["id"] == id:
                return MagicMock(execute=MagicMock(return_value=m))
        return MagicMock(execute=MagicMock(return_value={}))

    service.users().messages().get = MagicMock(side_effect=get_side_effect)
    return service


class TestFetchInteracEmails:
    def test_valid_interac_email_is_included(self):
        msg = _make_gmail_message(
            "1",
            f"Interac <{INTERAC_SENDER}>",
            "Interac e-Transfer: You've received $500.00 from JOHN SMITH and it has been automatically deposited.",
            "",
        )
        service = _mock_service([msg])
        transfers = fetch_interac_emails(service, "2026/02/26")
        assert len(transfers) == 1
        assert transfers[0]["sender"] == "JOHN SMITH"
        assert transfers[0]["amount"] == 500.00

    def test_non_interac_sender_is_filtered_out(self):
        msg = _make_gmail_message(
            "1",
            "scammer@evil.com",
            "Interac e-Transfer: You've received $500.00 from JOHN SMITH and it has been automatically deposited.",
            "",
        )
        service = _mock_service([msg])
        transfers = fetch_interac_emails(service, "2026/02/26")
        assert len(transfers) == 0

    def test_mixed_valid_and_invalid_senders(self):
        valid = _make_gmail_message(
            "1",
            f"{INTERAC_SENDER}",
            "Interac e-Transfer: You've received $360.00 from CHRISTIANE CHALFOUN and it has been automatically deposited.",
            "",
        )
        invalid = _make_gmail_message(
            "2",
            "fake@notinterac.com",
            "Interac e-Transfer: You've received $9999.00 from FAKE PERSON and it has been automatically deposited.",
            "",
        )
        service = _mock_service([valid, invalid])
        transfers = fetch_interac_emails(service, "2026/02/26")
        assert len(transfers) == 1
        assert transfers[0]["sender"] == "CHRISTIANE CHALFOUN"

    def test_no_messages_returned(self):
        service = MagicMock()
        service.users().messages().list().execute.return_value = {}
        transfers = fetch_interac_emails(service, "2026/02/26")
        assert transfers == []

    def test_unparseable_email_is_skipped(self):
        msg = _make_gmail_message(
            "1",
            f"{INTERAC_SENDER}",
            "Some random subject with no transfer info",
            "No useful content here",
        )
        service = _mock_service([msg])
        transfers = fetch_interac_emails(service, "2026/02/26")
        assert len(transfers) == 0

    def test_before_date_parameter(self):
        msg = _make_gmail_message(
            "1",
            f"{INTERAC_SENDER}",
            "Interac e-Transfer: You've received $500.00 from JOHN SMITH and it has been automatically deposited.",
            "",
        )
        service = _mock_service([msg])
        transfers = fetch_interac_emails(service, "2026/02/01", before_date="2026/03/01")
        assert len(transfers) == 1
