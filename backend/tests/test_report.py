from app.report import build_report, inr

CONFIRM = {"car": {"make": "Maruti Suzuki", "model": "Ertiga", "variant": "ZXi", "year": 2023, "fuel": "Petrol"},
           "plate": "MH14LA9829", "city": "Pimpri-Chinchwad", "state": "Maharashtra", "odometer_km": 110422,
           "changed": ["variant"], "skipped": [], "photos": []}
VERIFY = {"plate": {"text": "MH14LA9829", "source": "ocr"}, "findings": [
    {"item_id": "L3", "confirmed": True, "best_frame": "L3.jpg", "part": "front_right_tyre", "issue": "no visible damage",
     "tyre": {"position": "front_right", "tyre_score": 6, "tread": "fair"}},
    {"item_id": "L4", "confirmed": True, "best_frame": "L4.jpg", "part": "right_mirror", "issue": "no visible damage", "action": "none"},
    {"item_id": "L10", "confirmed": True, "best_frame": "L10.jpg", "part": "left_front_fender", "issue": "dent",
     "severity": "minor", "action": "repair", "description": "Dent."},
    {"item_id": "L7", "confirmed": False, "reason": "Reflection."}]}
MANIFEST = {"items": [{"item_id": "L3", "category": "tyre", "t_text": "00:04.1", "side": "right"},
                      {"item_id": "L4", "category": "mirror", "t_text": "00:04.1"},
                      {"item_id": "L10", "category": "damage", "t_text": "00:31.8"},
                      {"item_id": "L7", "category": "damage", "label": "dent rear door"}]}
LOCATE = [{"side": "front"}, {"side": "right"}, {"side": "interior"}]
QUERIES = {"parts": [{"part": "left_front_fender"}, {"part": "boot_lid"}], "tyres": [{"item_id": "L3", "tier": "minor_wear"}]}
PRICE = {"status": "ok", "new_price": {"value": 1334000, "type": "on_road", "variant_match": "exact", "sources": ["S13"]},
         "listings_used": [{"source": "S2", "year": 2023, "price": 1049000, "rate": 0.9234}],
         "repairs": {"items": [{"for": "left_front_fender", "cost": 2395, "max": 2395, "note": "median of 3 prices",
                                "sources": ["https://x"]},
                               {"for": "L3", "cost": 5000, "fixed": "minor_wear (config)"}], "total": 7395},
         "car_age_years": 3, "yearly_value_kept": {"median": 0.93, "max": 0.934},
         "fair_value": {"median": 1074000, "max": 1086000}, "after_repairs": {"median": 1067000, "max": 1079000}}
SOURCES = {"S13": {"title": "Ertiga price", "url": "https://n"}, "S2": {"title": "Used Ertiga", "url": "https://l"}}


def inp(**kw):
    return {"confirm": CONFIRM, "verify": VERIFY, "manifest": MANIFEST, "locate_items": LOCATE, "queries": QUERIES,
            "photos_answer": None, "price": PRICE, "sources": SOURCES, "km_min_confidence": 0.8, **kw}


def test_inr():
    assert inr(1060000) == "₹10,60,000" and inr(2395) == "₹2,395" and inr(999) == "₹999" and inr(110422) == "₹1,10,422"


def test_full_report():
    r = build_report(inp())
    assert r["price"]["low"] == 1067000 and r["price"]["new_price"]["sources"][0]["url"] == "https://n"
    assert r["price"]["listings_used"][0]["source"]["title"] == "Used Ertiga"
    assert [d["part"] for d in r["damage"]] == ["left_front_fender"]
    assert r["damage"][0]["frame"] == "02_frames/L10.jpg" and r["damage"][0]["time"] == "00:31.8"
    assert r["tyres"][0]["tier"] == "minor_wear" and r["tyres"][0]["from"] == "video"
    assert r["repairs"]["items"][1]["for"] == "front right tyre"
    assert r["repairs"]["cost_unavailable"] == ["boot lid"]
    assert r["coverage"]["sides_seen"] == ["front", "right"] and r["coverage"]["sides_not_seen"] == ["rear", "left"]
    assert r["coverage"]["tyres_not_seen"] == ["front_left", "rear_left", "rear_right"]
    assert r["coverage"]["not_confirmed"] == [{"item_id": "L7", "label": "dent rear door", "reason": "Reflection."}]
    s = r["condition_summary"]
    assert s[0] == "1 damage finding(s): minor dent on left front fender (repair)."
    assert "Checked, no damage: right mirror." in s and s[-1] == "Odometer: 1,10,422 km (read from the video)."


def test_photos_and_no_price():
    photos = {"photos": [{"slot": "front_right", "description": "Worn.", "tyre": {"tyre_score": 3, "tread": "worn"}},
                         {"slot": "odometer", "odometer_km": 120000, "confidence": 0.95}]}
    r = build_report(inp(photos_answer=photos, price=None))
    assert r["tyres"][0]["from"] == "photo" and r["tyres"][0]["frame"] == "05_photos/front_right.jpg"
    assert r["vehicle"]["odometer_km"] == 120000 and r["vehicle"]["km_from"] == "odometer photo (0.95)"
    assert r["price"] == {"status": "unavailable", "reason": "Pricing did not run for this run"}
    assert r["repairs"]["items"] == []
