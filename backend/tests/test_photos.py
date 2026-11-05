from app.photos import apply_photos, list_photos, validate_answer

VERIFY = [
    {"item_id": "L3", "confirmed": True, "tyre": {"position": "front_left", "tyre_score": 8, "tread": "good"}},
    {"item_id": "L4", "confirmed": False, "tyre": {"position": "rear_right"}},
    {"item_id": "L9", "confirmed": True, "part": "left_rear_door", "issue": "dent"},
]
CONFIRM = {"car": {"make": "Maruti Suzuki"}, "odometer_km": 40003}


def test_no_photos_changes_nothing():
    c, f, applied = apply_photos(CONFIRM, VERIFY, None, 0.8)
    assert c is CONFIRM and f is VERIFY
    assert applied == {"tyres_replaced": [], "tyres_added": [], "km": None}


def test_tyre_replaced_and_added_inputs_untouched():
    answer = {"photos": [
        {"slot": "front_left", "description": "Worn.", "tyre": {"tyre_score": 3, "tread": "worn"}},
        {"slot": "rear_right", "description": "Bald.", "tyre": {"tyre_score": 0, "tread": "bald"}},
        {"slot": "rear_left", "description": "Blurred.", "tyre": {"tyre_score": None, "tread": None}},  # unreadable: ignored
        {"slot": "boot", "tyre": {"tyre_score": 5}},                                                    # unknown slot
    ]}
    c, f, applied = apply_photos(CONFIRM, VERIFY, answer, 0.8)
    assert [x["item_id"] for x in f] == ["L4", "L9", "photo_front_left", "photo_rear_right"]
    assert f[2]["tyre"] == {"position": "front_left", "tyre_score": 3, "tread": "worn"} and f[2]["category"] == "tyre"
    assert applied["tyres_replaced"] == [{"slot": "front_left", "replaced": ["L3"]}]
    assert applied["tyres_added"] == ["rear_right"]           # L4 was not confirmed, so the photo adds the tyre
    assert len(VERIFY) == 3 and c is CONFIRM


def test_photo_km_only_when_confident():
    hi = {"photos": [{"slot": "odometer", "odometer_km": 45200, "confidence": 0.93}]}
    c, _, applied = apply_photos(CONFIRM, [], hi, 0.8)
    assert c["odometer_km"] == 45200 and c["km_source"] == "odometer photo (0.93)" and CONFIRM["odometer_km"] == 40003
    assert applied["km"]["used"] is True
    lo = {"photos": [{"slot": "odometer", "odometer_km": 45200, "confidence": 0.5}]}
    c, _, applied = apply_photos(CONFIRM, [], lo, 0.8)
    assert c is CONFIRM and applied["km"] == {"photo_km": 45200, "confidence": 0.5, "used": False, "confirm_km": 40003}


def test_list_and_validate(tmp_path):
    (tmp_path / "odometer.jpg").write_bytes(b"x")
    (tmp_path / "front_left.jpg").write_bytes(b"x")
    assert [p["slot"] for p in list_photos(tmp_path)] == ["front_left", "odometer"]
    assert validate_answer({"photos": []}) is None and validate_answer({"x": 1})
