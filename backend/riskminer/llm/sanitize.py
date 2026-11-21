"""Copy rules for user-visible model text (no em dash, no middle dot) and personal contact-data scrubbing
(CLAUDE.md invariant 9: no personal contact data in normalised tables or exports)."""
from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Polish phone numbers: +48 123 456 789, 123-456-789, (12) 345 67 89, tel. 123456789
PHONE = re.compile(r"(?:(?:\+|00)48[\s-]?)?(?:\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|\d{3}[\s-]?\d{3}[\s-]?\d{3})(?!\d)")
PHONE_CTX = re.compile(r"(?i)\b(tel|telefon|fax|kom|mobile|nr tel)\.?:?\s*")
SCRUB = "[dane kontaktowe usunięte]"


def copy_rules(s: str | None) -> str | None:
    """Em dash → ', ' (or '-' between digits), middle dot removed, double spaces collapsed."""
    if s is None:
        return None
    s = re.sub(r"(?<=\d)\s*—\s*(?=\d)", "-", s)
    s = re.sub(r"\s*—\s*", ", ", s)
    s = s.replace("·", " ").replace("‧", " ").replace("⋅", " ")
    s = re.sub(r" {2,}", " ", s)
    s = re.sub(r"\s+,", ",", s)
    return s.strip()


def has_contact(s: str | None) -> bool:
    if not s:
        return False
    if EMAIL.search(s):
        return True
    for m in PHONE.finditer(s):
        pre = s[max(0, m.start() - 12):m.start()]
        if PHONE_CTX.search(pre) or m.group().startswith(("+48", "0048")):
            return True
    return False


def scrub_contact(s: str | None) -> str | None:
    """Remove e-mails always; remove phone-like numbers only when labelled (tel., fax) or prefixed +48, so amounts and
    NIP-like identifiers in quotes stay intact."""
    if not s:
        return s
    s = EMAIL.sub(SCRUB, s)

    def _ph(m: re.Match) -> str:
        pre = s[max(0, m.start() - 12):m.start()]
        if PHONE_CTX.search(pre) or m.group().startswith(("+48", "0048")):
            return SCRUB
        return m.group()

    return PHONE.sub(_ph, s)


def clean_user_text(s: str | None) -> str | None:
    return copy_rules(scrub_contact(s))


def clean_obj(obj: Any, keys: tuple[str, ...] = ("title", "why", "answer", "text", "uncertain_reason", "value_text",
                                                 "label", "answer_template", "cannot_answer")) -> Any:
    """Apply copy rules to user-visible string fields of a nested dict/list (quotes are scrubbed separately)."""
    if isinstance(obj, dict):
        return {k: (copy_rules(v) if k in keys and isinstance(v, str) else clean_obj(v, keys)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(v, keys) for v in obj]
    return obj


KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z]{20,}|Bearer\s+[0-9A-Za-z._\-]{16,}")


def redact_secrets(s: str | None) -> str | None:
    return KEY_PATTERN.sub("[klucz ukryty]", s) if s else s
