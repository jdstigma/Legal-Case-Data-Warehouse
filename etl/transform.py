"""Small shared parsing/casting helpers used by the transform step.

SCDB's raw CSVs use empty strings and, in a few legacy rows, the literal
text "NULL" to mean missing; dates are M/D/YYYY.
"""

from datetime import datetime

_MISSING = {"", "NULL", "null"}


def to_int(value):
    value = (value or "").strip()
    if value in _MISSING:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def to_text(value):
    value = (value or "").strip()
    if value in _MISSING:
        return None
    return value


def to_date(value):
    value = (value or "").strip()
    if value in _MISSING:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None
