"""Place categories shared by the OSM importer and the nearby API.

Each category has a Greek label, an Overpass filter (fallback path) and a tag predicate (import path).
"""
from __future__ import annotations

import re

_KEP = re.compile(r"ΚΕΠ|Κ\.Ε\.Π|Εξυπηρέτησης Πολιτών")


def _eq(k, v):
    return lambda t: t.get(k) == v


def _in(k, vals):
    return lambda t: t.get(k) in vals


CATEGORIES: dict[str, dict] = {
    "fuel": {"label": "Βενζινάδικα", "filter": '["amenity"="fuel"]', "match": _eq("amenity", "fuel")},
    "charging": {"label": "Φορτιστές EV", "filter": '["amenity"="charging_station"]', "match": _eq("amenity", "charging_station")},
    "atm": {"label": "ATM", "filter": '["amenity"="atm"]', "match": _eq("amenity", "atm")},
    "bank": {"label": "Τράπεζες", "filter": '["amenity"="bank"]', "match": _eq("amenity", "bank")},
    "pharmacy": {"label": "Φαρμακεία", "filter": '["amenity"="pharmacy"]', "match": _eq("amenity", "pharmacy")},
    "supermarket": {"label": "Σούπερ μάρκετ", "filter": '["shop"="supermarket"]', "match": _eq("shop", "supermarket")},
    "bakery": {"label": "Φούρνοι", "filter": '["shop"="bakery"]', "match": _eq("shop", "bakery")},
    "kiosk": {"label": "Περίπτερα", "filter": '["shop"="kiosk"]', "match": _eq("shop", "kiosk")},
    "cafe": {"label": "Καφέ", "filter": '["amenity"="cafe"]', "match": _eq("amenity", "cafe")},
    "restaurant": {"label": "Εστιατόρια", "filter": '["amenity"~"^(restaurant|fast_food)$"]', "match": _in("amenity", {"restaurant", "fast_food"})},
    "bar": {"label": "Μπαρ", "filter": '["amenity"~"^(bar|pub)$"]', "match": _in("amenity", {"bar", "pub"})},
    "parking": {"label": "Πάρκινγκ", "filter": '["amenity"="parking"]["access"!="private"]', "match": lambda t: t.get("amenity") == "parking" and t.get("access") != "private"},
    "toilets": {"label": "Τουαλέτες", "filter": '["amenity"="toilets"]', "match": _eq("amenity", "toilets")},
    "water": {"label": "Βρύσες", "filter": '["amenity"="drinking_water"]', "match": _eq("amenity", "drinking_water")},
    "playground": {"label": "Παιδικές χαρές", "filter": '["leisure"="playground"]', "match": _eq("leisure", "playground")},
    "post": {"label": "Ταχυδρομεία", "filter": '["amenity"="post_office"]', "match": _eq("amenity", "post_office")},
    "kep": {"label": "ΚΕΠ", "filter": '["office"="government"]["name"~"ΚΕΠ|Κ.Ε.Π|Εξυπηρέτησης Πολιτών"]', "match": lambda t: t.get("office") == "government" and bool(_KEP.search(t.get("name", "")))},
    "church": {"label": "Εκκλησίες", "filter": '["amenity"="place_of_worship"]["religion"="christian"]', "match": lambda t: t.get("amenity") == "place_of_worship" and t.get("religion") == "christian"},
    "hospital": {"label": "Νοσοκομεία/κλινικές", "filter": '["amenity"~"^(hospital|clinic)$"]', "match": _in("amenity", {"hospital", "clinic"})},
    "beach": {"label": "Παραλίες", "filter": '["natural"="beach"]', "match": _eq("natural", "beach")},
    "taxi": {"label": "Πιάτσες ταξί", "filter": '["amenity"="taxi"]', "match": _eq("amenity", "taxi")},
    "bike": {"label": "Κοινόχρηστα ποδήλατα", "filter": '["amenity"="bicycle_rental"]', "match": _eq("amenity", "bicycle_rental")},
    "wifi": {"label": "Δωρεάν WiFi", "filter": '["internet_access"~"^(wlan|yes)$"]["internet_access:fee"~"^(no|customers)$"]', "match": lambda t: t.get("internet_access") in {"wlan", "yes"} and t.get("internet_access:fee") in {"no", "customers"} and not _is_private_venue(t)},
    "metro": {"label": "Σταθμοί μετρό/τραμ", "filter": '["railway"="station"]["station"~"^(subway|light_rail)$"]', "match": lambda t: t.get("railway") == "station" and t.get("station") in {"subway", "light_rail"} or t.get("railway") == "tram_stop"},
}


def _is_private_venue(t: dict) -> bool:
    """Free WiFi is interesting as a public amenity (squares, libraries, municipal spots), not as a café perk."""
    return t.get("amenity") in {"cafe", "restaurant", "bar", "pub", "fast_food", "hotel"} or t.get("tourism") == "hotel"


def categorize(tags: dict) -> str | None:
    for key, c in CATEGORIES.items():
        if c["match"](tags):
            return key
    return None
