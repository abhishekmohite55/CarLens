"""Markets (stage M0, docs/backend/07-us-market.md §3): every run is India ("in") or US ("us").

Pure helpers only: no config reads, no database, no events. Callers pass the values in.
"""
from __future__ import annotations

from typing import Any, Mapping

MARKETS = ("in", "us")
LABELS = {"in": "India", "us": "US"}

# US pipeline steps a stop can name (dev.stop_after_us). "upload" = upload/vin: video + VIN saved, locate never starts.
US_NODES = ("upload", "vin_details", "locate", "frames", "verify", "plan", "search", "extract", "pricing", "report")

# Keys that lived in shared sections before stage M0 → their place under markets.in.
_OLD_KEYS = (
    ("plan", "listing_templates", ("listing_templates",)),
    ("plan", "new_price_templates", ("new_price_templates",)),
    ("search", "country", ("search_country",)),
    ("extract", "listing_min_inr", ("extract_limits", "listing_min")),
    ("extract", "listing_max_inr", ("extract_limits", "listing_max")),
    ("pricing", "tyre_minor_wear_deduction_inr", ("tyre_minor_wear_deduction",)),
)


def move_market_keys(data: Any) -> Any:
    """A config saved before stage M0 (India keys in plan / search / extract / pricing) in the new shape: the keys are
    removed from their old sections and set under markets.in where markets.in does not have them yet (a value already
    under markets.in wins). The input is not changed. Anything that is not a dict comes back as it is."""
    if not isinstance(data, Mapping):
        return data
    out = dict(data)
    markets = dict(out["markets"]) if isinstance(out.get("markets"), Mapping) else None
    india = dict(markets.get("in") or {}) if markets else {}
    moved = False
    for section, key, target in _OLD_KEYS:
        if not isinstance(out.get(section), Mapping) or key not in out[section]:
            continue
        out[section] = dict(out[section])
        value = out[section].pop(key)
        moved = True
        if len(target) == 1:
            india.setdefault(target[0], value)
        else:
            limits = dict(india.get(target[0]) or {})
            limits.setdefault(target[1], value)
            india[target[0]] = limits
    if not moved:
        return out
    india.setdefault("currency", "INR")
    india.setdefault("distance_unit", "km")
    out["markets"] = {**(markets or {}), "in": india}
    return out


def resolve_market(*, user_market: str | None, is_admin: bool, admin_choice: str | None, country: str | None,
                   country_map: Mapping[str, str], default: str) -> str:
    """The market for a visitor, first that applies (07-us-market.md §3): the admin's pin on the user, the admin's own
    switch (admin only), the CloudFront country header through country_map, the default. Unknown values are skipped."""
    if user_market in MARKETS:
        return user_market
    if is_admin and admin_choice in MARKETS:
        return admin_choice
    mapped = country_map.get((country or "").strip().upper())
    if mapped in MARKETS:
        return mapped
    return default if default in MARKETS else "in"


def market_is_on(markets_on: Mapping[str, bool], market: str) -> bool:
    """dev.markets_on: a market missing from the map counts as off (a new market starts closed)."""
    return bool(markets_on.get(market, False))


def stop_after_for(market: str, stop_after_in: str | None, stop_after_us: str | None) -> str | None:
    """The stop setting of the run's market (dev.stop_after for India, dev.stop_after_us for US)."""
    return (stop_after_us if market == "us" else stop_after_in) or None


def past_stop(node: str, stop: str | None, order: tuple[str, ...]) -> bool:
    """True when `node` must not run because the pipeline stops before it. "upload" stops before every graph node."""
    if not stop:
        return False
    if stop == "upload":
        return True
    return stop in order and node in order and order.index(node) > order.index(stop)


def checked_market(value: str | None) -> str | None:
    """A market filter from a query string: "in" / "us", or None for all (empty, "all" or anything unknown)."""
    return value if value in MARKETS else None


# US states + DC (stage U1, 07-us-market.md §5): state chips and type-ahead on the US first screen.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}


def state_guess(region: str | None) -> str | None:
    """CloudFront-Viewer-Country-Region ("CA") → a US state code, or None when it is not one."""
    code = (region or "").strip().upper()
    return code if code in US_STATES else None
