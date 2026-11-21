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


# ---- script check: Polish output must use Latin letters only ------------------------------------------------------
_LATIN_OK = set("µºª")
AUTHORED_KEYS = {"title", "why", "answer", "summary", "text", "value_text", "uncertain_reason", "rationale", "definition",
                 "name", "answer_template", "cannot_answer", "label", "doc_kind", "question", "follow_ups", "missing"}


def non_latin(s: str | None) -> str:
    """Letters outside the Latin script (Cyrillic, Greek, CJK, Arabic, ...) found in s, deduplicated, in order."""
    import unicodedata
    out: list[str] = []
    for ch in s or "":
        if ch.isalpha() and ch not in _LATIN_OK and not unicodedata.name(ch, "").startswith("LATIN") and ch not in out:
            out.append(ch)
    return "".join(out)


def script_violations(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """(path, letters) for model-authored string fields with non-Latin letters. Verbatim quotes are not checked here:
    they are verified against the source page."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if k in AUTHORED_KEYS and isinstance(v, str):
                bad = non_latin(v)
                if bad:
                    found.append((p, bad))
            elif k in AUTHORED_KEYS and isinstance(v, list) and all(isinstance(x, str) for x in v):
                for i, x in enumerate(v):
                    bad = non_latin(x)
                    if bad:
                        found.append((f"{p}[{i}]", bad))
            else:
                found += script_violations(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += script_violations(v, f"{path}[{i}]")
    return found


def drop_script_violations(obj: Any) -> tuple[Any, int, bool]:
    """Remove list elements (items, notes, chips, strings) that carry non-Latin letters in authored fields.
    Returns (cleaned, n_dropped, top_level_violation_left)."""
    dropped = 0

    def clean(o: Any, top: bool) -> Any:
        nonlocal dropped
        if isinstance(o, dict):
            return {k: clean(v, False) for k, v in o.items()}
        if isinstance(o, list):
            keep = []
            for v in o:
                if (isinstance(v, (dict, list)) and script_violations(v)) or (isinstance(v, str) and non_latin(v)):
                    dropped += 1
                    continue
                keep.append(clean(v, False))
            return keep
        return o

    cleaned = clean(obj, True)
    return cleaned, dropped, bool(script_violations(cleaned))
