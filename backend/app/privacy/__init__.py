"""
Privacy module — PII detection and redaction for user messages.

Usage:
    from app.privacy.pii_redactor import redact_pii

    redacted_text, detections = redact_pii("My name is John, call me at 212-555-1234")
    # redacted_text = "My name is [NAME], call me at [PHONE]"
    # detections = [PII(NAME, ...), PII(PHONE, ...)]
"""
