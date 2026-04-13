"""
watchlist.py — Curated list of expert accounts Arkiveit monitors.
Add or remove accounts here. Handles are without the @ symbol.
"""

WATCHLIST = [
    # Finance / Markets
    "elerianm",        # Mohamed El-Erian — macro economist
    "morganhousel",    # Morgan Housel — finance author
    "ritholtz",        # Barry Ritholtz — wealth management
    "LizAnnSonders",   # Liz Ann Sonders — Schwab chief strategist
    "KobeissiLetter",  # The Kobeissi Letter — markets
    "jimcramer",       # Jim Cramer — CNBC (high signal for contrarian tracking)
    "RaoulGMI",        # Raoul Pal — macro / crypto
    "LukeGromen",      # Luke Gromen — macro / dollar

    # Politics / Policy
    "ianbremmer",      # Ian Bremmer — geopolitical risk
    "benshapiro",      # Ben Shapiro — political commentary
    "tuckercarlson",   # Tucker Carlson — political commentary

    # Geopolitics
    "PeterZeihan",     # Peter Zeihan — geopolitics / demographics
    "Chellaney",       # Brahma Chellaney — Asia geopolitics
    "vtchakarova",     # Velina Tchakarova — geopolitics

    # Wild cards (high follower, frequent predictions)
    "_The_Prophet__",  # High-follower prediction account
]

# Category mapping for dashboard filtering
WATCHLIST_CATEGORIES = {
    "elerianm": "finance",
    "morganhousel": "finance",
    "ritholtz": "finance",
    "LizAnnSonders": "finance",
    "KobeissiLetter": "finance",
    "jimcramer": "finance",
    "RaoulGMI": "finance",
    "LukeGromen": "finance",
    "ianbremmer": "geopolitics",
    "benshapiro": "politics",
    "tuckercarlson": "politics",
    "AOC": "politics",
    "PeterZeihan": "geopolitics",
    "Chellaney": "geopolitics",
    "vtchakarova": "geopolitics",
    "_The_Prophet__": "finance",
}
