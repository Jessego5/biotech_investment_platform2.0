"""
This writes a figure down with the unit it was reported in, which is not
separable from what the figure is.

XBRL keys every fact by unit and this universe is not all American: Novo Nordisk
reports in kroner, Takeda in yen, and a filter for "over a billion in cash" that
compares those raw numbers against dollars lets them in on the exchange rate
rather than on the money. So a value carries its unit from the SEC response to
the column to the screen, comparisons against a dollar threshold are restricted
to dollars, and anything shown to a reader says which currency it is in.

Nothing here converts. A converted figure is no longer the figure the filing
reported, and this system's whole claim is that the number on screen is the one
in the document.
"""

# Symbols only where the symbol is unambiguous. "kr" is Danish, Swedish and
# Norwegian krone at once, which is exactly the confusion this module exists to
# end, so everything outside this map is written with its ISO code.
SYMBOLS = {"USD": "$", "EUR": "€", "JPY": "¥", "GBP": "£"}

# What the code stands for, spelled out. A reader who knows what $ means does
# not necessarily know SGD from SEK, and a three-letter code is only provenance
# to someone who already has it memorised. Every currency this universe actually
# files in is here; anything else falls back to its code, which is still true.
NAMES = {
    "USD": "US dollars",
    "EUR": "euro",
    "GBP": "pounds sterling",
    "JPY": "Japanese yen",
    "DKK": "Danish kroner",
    "SEK": "Swedish kronor",
    "NOK": "Norwegian kroner",
    "CHF": "Swiss francs",
    "CAD": "Canadian dollars",
    "AUD": "Australian dollars",
    "NZD": "New Zealand dollars",
    "SGD": "Singapore dollars",
    "HKD": "Hong Kong dollars",
    "ILS": "Israeli shekels",
    "INR": "Indian rupees",
    "CNY": "Chinese yuan",
    "KRW": "South Korean won",
    "TWD": "Taiwan dollars",
    "BRL": "Brazilian reais",
    "MXN": "Mexican pesos",
    "ZAR": "South African rand",
    "PLN": "Polish zloty",
}


def name_of(unit):
    """The currency spelled out, or the code itself where it is not known."""
    if not unit:
        return "an unrecorded unit"
    return NAMES.get(unit, unit)

# XBRL units that are not money. A share count is a count.
COUNTS = ("shares", "pure")

DOLLARS = "USD"


def is_money(unit):
    """Whether this unit is a currency at all."""
    return bool(unit) and unit not in COUNTS


def is_dollars(unit):
    """
    Whether a figure can be compared against a dollar amount.

    Null is not dollars. A row stored before the unit was kept has an unknown
    unit, and treating unknown as USD is how the wrong answer got out in the
    first place.
    """
    return unit == DOLLARS


def _write(written, unit, name):
    """The figure with its unit, and optionally with that unit spelled out."""
    if not unit:
        return f"{written} (unit not recorded)"
    if unit in COUNTS:
        return f"{written} {unit}"
    symbol = SYMBOLS.get(unit)
    figure = f"{symbol}{written}" if symbol else f"{unit} {written}"
    # dollars need no gloss, and repeating one on every row of a table would
    # bury the figures it is there to qualify
    if name and unit != DOLLARS:
        return f"{figure} ({name_of(unit)})"
    return figure


def money(value, unit, name=False):
    """
    One figure, written so it cannot be read as the wrong currency.

    A unit that was never recorded says so rather than borrowing a dollar sign.
    Pass name=True where the figure stands on its own and the reader has no
    other cue: "DKK 26,464,000,000 (Danish kroner)".
    """
    if value is None:
        return "n/a"
    return _write(f"{int(value):,}", unit, name)


def millions(value, unit, name=False):
    """The same, rounded to millions, for tables and one-line summaries."""
    if value is None:
        return "n/a"
    return _write(f"{round(value / 1e6):,}M", unit, name)


def same_unit(*figures):
    """
    Whether these figures can be added or divided by one another.

    Two figures in different currencies are not a sum and not a ratio. Where a
    company's cash and its burn disagree, there is no runway to compute, and
    saying nothing is the only honest answer available.
    """
    seen = {f.get("unit") for f in figures if f}
    return len(seen) <= 1
