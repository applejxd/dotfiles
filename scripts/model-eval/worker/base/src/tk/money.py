"""Money amounts as Decimal, formatted in US style."""

import re
from decimal import ROUND_HALF_UP, Decimal

_PATTERN = re.compile(r"^(-)?\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?$")


def to_cents(amount: Decimal) -> int:
    """Round to whole cents, half away from zero (0.005 -> 1, -0.005 -> -1)."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_money(amount: Decimal) -> str:
    """Format as e.g. ``$1,234.50`` or ``-$0.05``."""
    cents = to_cents(amount)
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rem:02d}"


def parse_money(text: str) -> Decimal:
    """Parse ``$1,234.5``, ``1234.5``, ``-$3`` (surrounding spaces allowed)."""
    m = _PATTERN.match(text.strip())
    if not m:
        raise ValueError(f"invalid amount: {text!r}")
    sign, whole, frac = m.groups()
    value = Decimal(whole.replace(",", "") + ("." + frac if frac else ""))
    return -value if sign else value
