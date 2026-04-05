"""
PII Redaction Pipeline

Detects and redacts personally identifiable information from user messages
BEFORE they are stored in session state or logged anywhere.

Architecture: This runs on every incoming message. The original text is used
for slot extraction (so "I'm in Brooklyn" still works), but only the redacted
version is stored in the session transcript.

PII categories handled:
    - Phone numbers       → [PHONE]
    - Social Security #s  → [SSN]
    - Email addresses     → [EMAIL]
    - Dates of birth      → [DOB]
    - Street addresses    → [ADDRESS]
    - Names (heuristic)   → [NAME]

Design decisions:
    - Regex-first for structured PII (phone, SSN, email) — high precision.
    - Heuristic pattern matching for names — moderate precision, avoids
      false positives on NYC place names (Brooklyn, Queens, etc.).
    - No heavy dependencies (no spaCy, no Presidio) — keeps deploy simple.
    - Returns both the redacted text and a list of what was found, so the
      caller can log the detection without logging the PII itself.
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII PATTERNS
# ---------------------------------------------------------------------------

# Phone numbers: (212) 555-1234, 212-555-1234, 212.555.1234, 2125551234, +1 212 555 1234
_PHONE_PATTERN = re.compile(
    r"""
    (?:(?:\+?1[\s.-]?)?                # optional country code
    (?:\(?\d{3}\)?[\s.-]?)             # area code
    \d{3}[\s.-]?\d{4})                 # subscriber number
    """,
    re.VERBOSE,
)

# SSN: 123-45-6789, 123 45 6789, 123456789
_SSN_PATTERN = re.compile(
    r"\b\d{3}[\s-]?\d{2}[\s-]?\d{4}\b"
)

# Email: user@example.com
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

# Dates of birth: 01/15/1990, 1/15/90, 01-15-1990, January 15 1990, Jan 15, 1990
_DOB_PATTERNS = [
    # MM/DD/YYYY or M/D/YY
    re.compile(r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b"),
    # Month DD, YYYY or Month DD YYYY
    re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|"
        r"Nov|Dec)[\s.]+\d{1,2}[\s,]+\d{2,4}\b",
        re.IGNORECASE,
    ),
]

# Street addresses: "123 Main Street", "456 Broadway", "789 Flatbush Ave"
#
# Uses full suffix words plus safe abbreviations. 'St' and 'Ter' are safe
# because the full pattern requires a leading number + capitalized word,
# which eliminates false positives like "status", "still", "shelter", etc.
_STREET_SUFFIX = (
    r"(?:Street|St\.|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|"
    r"Lane|Ln|Place|Pl|Court|Ct|Way|Terrace|Ter\.?)"
)

# Optional apartment/unit/floor suffix: "Apt 4B", "#12", "Unit 3", "Fl 2"
_UNIT_SUFFIX = (
    r"(?:\s+(?:Apt\.?|Unit|Suite|Ste\.?|Fl(?:oor)?\.?|Rm\.?|#)\s*[A-Za-z0-9-]+)?"
)

_ADDRESS_PATTERNS = [
    # Standard: number + word-based street name(s) + suffix + optional unit
    # e.g. "300 Lafayette Street", "456 West Main Street Apt 4B"
    re.compile(
        r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
        + _STREET_SUFFIX + _UNIT_SUFFIX + r"\b",
        re.IGNORECASE,
    ),
    # Ordinal street: number + optional direction + ordinal + suffix + optional unit
    # e.g. "456 West 42nd Street", "789 5th Avenue Apt 3"
    re.compile(
        r"\b\d{1,5}\s+(?:(?:East|West|North|South|E|W|N|S)\s+)?"
        r"\d{1,3}(?:st|nd|rd|th)\s+"
        + _STREET_SUFFIX + _UNIT_SUFFIX + r"\b",
        re.IGNORECASE,
    ),
    # Broadway special case (no suffix needed) + optional unit
    re.compile(
        r"\b\d{1,5}\s+Broadway" + _UNIT_SUFFIX + r"\b",
        re.IGNORECASE,
    ),
    # Suffix-less addresses with location preposition context:
    # "at 123 Main", "on 456 Flatbush". Requires a preposition to avoid
    # false positives on bare "number + word" phrases like "5 Borough".
    re.compile(
        r"(?:at|on|to)\s+\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
        + _UNIT_SUFFIX + r"\b",
        re.IGNORECASE,
    ),
]

# Name patterns — heuristic based on common intro phrases.
# "My name is John Smith", "I'm John", "call me Maria", etc.
# We extract what follows these intro phrases as a likely name.
# re.IGNORECASE on the intro so "My name is" and "my name is" both work.
# The capture group still targets capitalized words as likely names.
_NAME_INTRO_PATTERNS = [
    re.compile(r"\bmy name is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bname'?s?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bi'?m\s+([A-Z][a-z]+)\b(?!\s+(?:in|at|from|looking|trying|a|an|the|so|not|very|really|just|\d))", re.IGNORECASE),
    re.compile(r"\bcall me\s+([A-Z][a-z]+)", re.IGNORECASE),
    re.compile(r"\bthis is\s+([A-Z][a-z]+)", re.IGNORECASE),
]

# Words that look like names but aren't — NYC places, service keywords, etc.
# These prevent false positives like "I'm in Queens" → [NAME] Queens.
# With IGNORECASE on the patterns, short common words also need blocking.
_NAME_BLOCKLIST = {
    # Boroughs and neighborhoods
    "manhattan", "brooklyn", "queens", "bronx", "staten",
    "harlem", "midtown", "soho", "tribeca", "chelsea",
    "williamsburg", "bushwick", "astoria", "flushing", "jamaica",
    "fordham", "inwood", "flatbush", "brownsville",
    "chinatown", "dumbo", "gramercy", "nolita", "noho",
    "corona", "elmhurst", "ridgewood", "woodside", "sunnyside",
    "morrisania",
    # Common non-name words that might match with IGNORECASE
    "in", "at", "on", "to", "so", "up", "ok", "an", "or", "if",
    "looking", "trying", "searching", "hoping", "needing",
    "hungry", "homeless", "tired", "sick", "lost", "scared",
    "good", "fine", "okay", "here", "back", "done", "safe",
    "not", "just", "also", "still", "very", "really",
    # Service words
    "food", "shelter", "clothing", "medical", "legal",
}


# ---------------------------------------------------------------------------
# DETECTION + REDACTION
# ---------------------------------------------------------------------------

class PIIDetection:
    """A single detected PII instance."""
    def __init__(self, pii_type: str, start: int, end: int, original: str):
        self.pii_type = pii_type
        self.start = start
        self.end = end
        self.original = original

    def __repr__(self):
        return f"PII({self.pii_type}, pos={self.start}-{self.end})"


def detect_pii(text: str) -> List[PIIDetection]:
    """
    Scan text for PII and return a list of detections.

    Does NOT modify the text — use redact_pii() for that.
    """
    detections = []

    # SSN (check before phone to avoid overlap — SSNs are 9 digits)
    for match in _SSN_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        # SSNs are exactly 9 digits in the XXX-XX-XXXX pattern.
        # The regex already enforces the 3-2-4 grouping structure.
        if len(digits) == 9:
            detections.append(PIIDetection("SSN", match.start(), match.end(), match.group()))

    # Email
    for match in _EMAIL_PATTERN.finditer(text):
        detections.append(PIIDetection("EMAIL", match.start(), match.end(), match.group()))

    # Phone
    for match in _PHONE_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        # Must be 10-11 digits to be a real phone number
        if 10 <= len(digits) <= 11:
            # Skip if this span was already matched as an SSN
            if not _overlaps(detections, match.start(), match.end()):
                detections.append(PIIDetection("PHONE", match.start(), match.end(), match.group()))

    # DOB
    for pattern in _DOB_PATTERNS:
        for match in pattern.finditer(text):
            if not _overlaps(detections, match.start(), match.end()):
                detections.append(PIIDetection("DOB", match.start(), match.end(), match.group()))

    # Street address
    for pattern in _ADDRESS_PATTERNS:
        for match in pattern.finditer(text):
            if not _overlaps(detections, match.start(), match.end()):
                detections.append(PIIDetection("ADDRESS", match.start(), match.end(), match.group()))

    # Names (heuristic — lower confidence, so we check blocklist)
    for pattern in _NAME_INTRO_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1)
            if candidate.lower() not in _NAME_BLOCKLIST:
                full_start = match.start(1)
                full_end = match.end(1)
                if not _overlaps(detections, full_start, full_end):
                    detections.append(PIIDetection("NAME", full_start, full_end, candidate))

    # Sort by position for clean left-to-right redaction
    detections.sort(key=lambda d: d.start)

    return detections


def redact_pii(text: str) -> Tuple[str, List[PIIDetection]]:
    """
    Detect and replace PII with typed placeholders.

    Returns:
        (redacted_text, list_of_detections)

    Example:
        >>> redact_pii("My name is John and my number is 212-555-1234")
        ("My name is [NAME] and my number is [PHONE]", [PII(NAME,...), PII(PHONE,...)])
    """
    detections = detect_pii(text)

    if not detections:
        return text, []

    # Build redacted string by replacing from right to left
    # (so earlier indices aren't shifted by replacements)
    redacted = text
    for det in reversed(detections):
        placeholder = f"[{det.pii_type}]"
        redacted = redacted[:det.start] + placeholder + redacted[det.end:]

    if detections:
        logger.info(
            f"Redacted {len(detections)} PII instance(s): "
            f"{[d.pii_type for d in detections]}"
        )

    return redacted, detections


def has_pii(text: str) -> bool:
    """Quick check: does this text contain any detectable PII?"""
    return len(detect_pii(text)) > 0


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _overlaps(detections: List[PIIDetection], start: int, end: int) -> bool:
    """Check if a span overlaps with any existing detection."""
    for d in detections:
        if start < d.end and end > d.start:
            return True
    return False
