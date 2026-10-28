"""The epoch texts S-0096 measured, and the instant each must read as on every
port that ships the formats (S-0096/D-4, D-6, D-7). One table, so DuckDB's
execution test and the engine differential cannot hold different answers."""

from __future__ import annotations

from datetime import datetime

__all__ = ["MILLIS", "SECONDS"]

SECONDS: dict[str | None, datetime | None] = {
    "1761561600": datetime(2025, 10, 27, 10, 40),
    "0": datetime(1970, 1, 1),
    "-1": datetime(1969, 12, 31, 23, 59, 59),
    " 1761561600 ": datetime(2025, 10, 27, 10, 40),
    "+1761561600": datetime(2025, 10, 27, 10, 40),
    "253402300799": datetime(9999, 12, 31, 23, 59, 59),
    "-62135596800": datetime(1, 1, 1),
    # Out of range, a fraction, an exponent, not a number, too wide: NULL.
    "253402300800": None,
    "1761561600123": None,
    "1761561600.5": None,
    "1.7615616E9": None,
    "abc": None,
    "99999999999999999": None,
    None: None,
}

MILLIS: dict[str | None, datetime | None] = {
    "1761561600123": datetime(2025, 10, 27, 10, 40, 0, 123000),
    "1761561600": datetime(1970, 1, 21, 9, 19, 21, 600000),
    "-1": datetime(1969, 12, 31, 23, 59, 59, 999000),
    "253402300799999": datetime(9999, 12, 31, 23, 59, 59, 999000),
    "253402300800000": None,
    "1761561600123.5": None,
    "abc": None,
    None: None,
}
