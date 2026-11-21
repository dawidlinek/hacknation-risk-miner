import pytest

from riskminer.llm.sanitize import copy_rules, has_contact, redact_secrets, scrub_contact

pytestmark = pytest.mark.unit


def test_copy_rules():
    assert copy_rules("Ryczałt — ryzyko") == "Ryczałt, ryzyko"
    assert copy_rules("strony 13—18") == "strony 13-18"
    assert "·" not in copy_rules("a · b")


def test_contact_scrub_keeps_amounts():
    s = "Projektant: jan.kowalski@example.pl, tel. 601 234 567. Wartość 1 234 567 zł, NIP 123 456 789"
    out = scrub_contact(s)
    assert "example.pl" not in out and "601 234 567" not in out
    assert "1 234 567 zł" in out and "NIP 123 456 789" in out
    assert has_contact(s) and not has_contact("Wartość 7 mln zł")


def test_secret_redaction():
    assert "AIza" not in redact_secrets("error key=AIzaSyA1234567890abcdefghijklmnop end")
