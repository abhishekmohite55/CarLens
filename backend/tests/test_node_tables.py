"""A table per node: locate_items and frames (platform stage 2.3b)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import node_tables, results, run_index

LOCATE = {"parsed": {"items": [
    {"id": "L1", "category": "plate", "label": "front plate", "side": "front", "t": 1.0, "t_text": "00:01.0"},
    {"id": "L2", "category": "damage", "label": "dent on left door", "side": "left", "t": 9.5, "t_text": "00:09.5"}],
    "coverage": {}}}
MANIFEST = {"items": [
    {"item_id": "L1", "frames_extracted": 45, "sharpest": {"t": 0.17, "sharpness": 4405.0, "file": "L1_plate.jpg"}},
    {"item_id": "L2", "skipped": "no frame could be read"}]}


def test_rows_from_json():
    assert [r["item_id"] for r in node_tables.locate_rows(LOCATE)] == ["L1", "L2"]
    assert node_tables.locate_rows({"parsed": None}) == []
    rows = node_tables.frame_rows(MANIFEST)
    assert rows[0] == {"item_id": "L1", "file": "L1_plate.jpg", "t": 0.17, "sharpness": 4405.0,
                       "frames_scored": 45, "skipped": None}
    assert rows[1]["skipped"] == "no frame could be read" and rows[1]["file"] is None


def test_saving_json_fills_the_node_tables_and_rerun_clears_them(db_engine):
    from sqlalchemy import func, select

    from app.models import Frame, LocateItem

    run_id = run_index.create_run_row(sha256="bb" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "01_locate/response.json", LOCATE)
    results.save_result(run_id, "02_frames/manifest.json", MANIFEST)

    def count(model):
        with db_engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(model).where(model.run_id == run_id)).scalar()

    assert (count(LocateItem), count(Frame)) == (2, 2)
    results.save_result(run_id, "01_locate/response.json", LOCATE)  # saved again: replaced, not doubled
    assert count(LocateItem) == 2
    results.delete_results(run_id, "locate")  # locate re-run: its items go, and the frames that hang off them
    assert (count(LocateItem), count(Frame)) == (0, 0)


VERIFY = {"answered_by": {"provider": "openrouter", "model": "nvidia/nemotron"}, "parsed": {
    "findings": [
        {"item_id": "L2", "confirmed": True, "part": "left_front_door", "issue": "dent", "severity": "minor",
         "action": "repair", "description": "small dent", "best_frame": "L2.jpg"},
        {"item_id": "L1", "confirmed": True, "part": "front_left_tyre", "issue": "no visible damage",
         "tyre": {"position": "front_left", "tyre_score": "7", "tread": "fair"}},
        {"item_id": "L99", "confirmed": False, "reason": "not an item locate gave"}],
    "plate": {"text": "MH14LA9829", "confidence": 0.9, "source": "ocr"},
    "badge": {"text": "ERTIGA"}, "odometer_km": {"value": 110422.0},
    "vehicle": {"make": {"value": "Maruti Suzuki"}, "model": {"value": "Ertiga"}, "variant": {"value": None},
                "year": {"value": 2023}, "fuel": {"value": "Petrol"}}}}


def test_verify_rows_from_json():
    rows = node_tables.finding_rows(VERIFY["parsed"])
    assert rows[1]["tyre_score"] == 7 and rows[1]["tyre_position"] == "front_left"
    v = node_tables.vehicle_row(VERIFY)
    assert (v["model"], v["year"], v["plate"], v["odometer_km"], v["answered_by"]) == \
        ("Ertiga", 2023, "MH14LA9829", 110422, "nvidia/nemotron")
    assert node_tables.vehicle_row({"parsed": None}) is None


def test_saving_verify_fills_findings_and_vehicle(db_engine):
    from sqlalchemy import select

    from app.models import VerifyFinding, VerifyVehicle

    run_id = run_index.create_run_row(sha256="cc" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "01_locate/response.json", LOCATE)
    results.save_result(run_id, "03_verify/response.json", VERIFY)
    with db_engine.connect() as conn:
        items = conn.execute(select(VerifyFinding.item_id).where(VerifyFinding.run_id == run_id)
                             .order_by(VerifyFinding.item_id)).scalars().all()
        make = conn.execute(select(VerifyVehicle.make).where(VerifyVehicle.run_id == run_id)).scalar()
    assert items == ["L1", "L2"]  # L99 is not a locate item: JSON only
    assert make == "Maruti Suzuki"
    results.delete_results(run_id, "verify")
    with db_engine.connect() as conn:
        assert conn.execute(select(VerifyVehicle).where(VerifyVehicle.run_id == run_id)).first() is None
