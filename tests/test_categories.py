from simera.categories import CATEGORIES, categorize


def test_categorize():
    assert categorize({"amenity": "fuel", "brand": "BP"}) == "fuel"
    assert categorize({"amenity": "parking", "access": "private"}) is None
    assert categorize({"amenity": "parking"}) == "parking"
    assert categorize({"office": "government", "name": "ΚΕΠ Κυψέλης"}) == "kep"
    assert categorize({"office": "government", "name": "ΔΟΥ Α' Αθηνών"}) is None
    assert categorize({"amenity": "place_of_worship", "religion": "christian"}) == "church"
    assert categorize({"shop": "bakery"}) == "bakery"
    assert categorize({"highway": "bus_stop"}) is None
    assert categorize({"internet_access": "wlan", "internet_access:fee": "no", "leisure": "park"}) == "wifi"
    assert categorize({"internet_access": "wlan", "internet_access:fee": "no", "shop": "clothes"}) is None  # a shop's WiFi is not a public hotspot
    assert categorize({"internet_access": "wlan", "internet_access:fee": "no", "amenity": "cafe"}) == "cafe"


def test_every_category_has_label_filter_and_match():
    for k, c in CATEGORIES.items():
        assert c["label"] and c["filter"].startswith("[") and callable(c["match"]), k
