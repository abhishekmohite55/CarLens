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


RECORD = {"car": {"make": "Maruti Suzuki", "model": "Ertiga", "variant": "ZXi", "year": 2023, "fuel": "Petrol"},
          "plate": "MH14LA9829", "city": "Pimpri-Chinchwad", "state": "Maharashtra", "odometer_km": 110422,
          "changed": ["variant", "year"], "skipped": [], "photos": [], "confirmed_at": "2026-11-10T08:00:00Z"}


def test_confirm_record_fills_confirmed_cars(db_engine):
    from sqlalchemy import select

    from app.models import ConfirmedCar

    row = node_tables.confirmed_row(RECORD)
    assert row["changed"] == ["variant", "year"] and row["confirmed_at"].year == 2026
    run_id = run_index.create_run_row(sha256="dd" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "04_confirm.json", RECORD)
    with db_engine.connect() as conn:
        car = conn.execute(select(ConfirmedCar).where(ConfirmedCar.run_id == run_id)).one()
    assert (car.model, car.city, car.changed) == ("Ertiga", "Pimpri-Chinchwad", ["variant", "year"])


def test_rto_rows_come_from_the_database(db_engine):
    from sqlalchemy import delete, insert

    from app.models import RtoCode, State
    from app.nodes.confirm import rto_rows

    with db_engine.begin() as conn:  # carlens_test has no seed: two rows of our own
        conn.execute(delete(RtoCode)), conn.execute(delete(State))
        conn.execute(insert(State).values(code="MH", name="Maharashtra"))
        conn.execute(insert(RtoCode), [{"state_code": "MH", "number": "14", "city": "Pimpri-Chinchwad", "statewide": False},
                                       {"state_code": "MH", "number": "08AA", "city": "Letter code", "statewide": False}])
    assert rto_rows() == [{"state_code": "MH", "number": 14, "state": "Maharashtra", "city": "Pimpri-Chinchwad"}]


PHOTOS_RESPONSE = {"answered_by": {"model": "gemini"}, "parsed": {"photos": [
    {"slot": "front_left", "description": "worn", "tyre": {"tyre_score": 3, "tread": "worn"}},
    {"slot": "odometer", "description": "cluster", "odometer_km": 45200, "confidence": 0.6}]}}
APPLIED = {"tyres_replaced": [{"slot": "front_left", "replaced": ["L4"]}], "tyres_added": [],
           "km": {"photo_km": 45200, "confidence": 0.6, "used": False, "confirm_km": 52054}}


def test_photo_rows_mark_what_was_used():
    rows = {r["slot"]: r for r in node_tables.photo_rows(PHOTOS_RESPONSE, APPLIED)}
    assert rows["front_left"]["used"] is True and rows["front_left"]["tyre_score"] == 3
    assert rows["odometer"]["used"] is False and rows["odometer"]["odometer_km"] == 45200  # confidence below 0.8


def test_saving_applied_fills_photo_results(db_engine):
    from sqlalchemy import select

    from app.models import PhotoResult

    run_id = run_index.create_run_row(sha256="ff" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "05_photos/response.json", PHOTOS_RESPONSE)
    results.save_result(run_id, "05_photos/applied.json", APPLIED)
    with db_engine.connect() as conn:
        slots = conn.execute(select(PhotoResult.slot).where(PhotoResult.run_id == run_id)
                             .order_by(PhotoResult.slot)).scalars().all()
    assert slots == ["front_left", "odometer"]


QUERIES = {"listing": ["used Maruti Suzuki Ertiga 2016 price in Thane"], "new_price": ["Ertiga VXi on road price"],
           "parts": [{"part": "front_bumper", "queries": ["front bumper price Ertiga"]}],
           "tyres": [{"item_id": "L4", "tier": "replace", "queries": ["Ertiga tyre price"]},
                     {"item_id": "L5", "tier": "minor_wear", "queries": []}]}


def test_plan_rows_one_per_query():
    rows = node_tables.plan_rows(QUERIES)
    assert [r["kind"] for r in rows] == ["listing", "new_price", "part", "tyre"]
    assert rows[3] == {"kind": "tyre", "for_item": "L4", "query": "Ertiga tyre price", "tier": "replace"}


def test_saving_queries_fills_plan_queries(db_engine):
    from sqlalchemy import func, select

    from app.models import PlanQuery

    run_id = run_index.create_run_row(sha256="ab" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "06_plan/queries.json", QUERIES)
    results.save_result(run_id, "06_plan/queries.json", QUERIES)  # re-run: replaced, not doubled
    with db_engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(PlanQuery).where(PlanQuery.run_id == run_id)).scalar()
    assert n == 4


SEARCH = {"queries": [
    {"kind": "listing", "for": None, "query": "used Ertiga Thane", "results": [
        {"title": "Ertiga 2016", "url": "https://a.example/1", "content": "Ertiga VXi 2016 Rs 6.2 Lakh", "score": 0.9},
        {"title": "dup", "url": "https://a.example/1", "content": "Ertiga VXi 2016 Rs 6.2 Lakh", "score": 0.8}]},
    {"kind": "part", "for": "front_bumper", "query": "bumper price", "results": [
        {"title": "Bumper", "url": "https://b.example/2", "content": "Front bumper Rs 3,500", "score": 0.7}]}]}


def test_name_key_and_search_rows():
    assert node_tables.name_key("Maruti Suzuki  Ertiga", "Maruti Suzuki") == "ertiga"
    assert node_tables.name_key("VXi") == "vxi" and node_tables.name_key(None) is None
    rows = node_tables.search_rows(SEARCH, {"make": "Maruti Suzuki", "model": "Ertiga", "year": 2016})
    assert len(rows) == 2  # same url + snippet twice in one run: once
    assert (rows[0]["make_key"], rows[0]["model_key"], rows[0]["year"]) == ("maruti suzuki", "ertiga", 2016)


def test_search_results_are_kept_and_only_dated_again(db_engine):
    from sqlalchemy import delete, func, select

    from app.models import SearchResult

    with db_engine.begin() as conn:
        conn.execute(delete(SearchResult).where(SearchResult.url.like("https://%.example/%")))
    run_id = run_index.create_run_row(sha256="ac" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "04_confirm.json", RECORD)
    results.save_result(run_id, "07_search/results.json", SEARCH)
    with db_engine.connect() as conn:
        first = conn.execute(select(func.max(SearchResult.last_seen_at))).scalar()
    results.save_result(run_id, "07_search/results.json", SEARCH)  # same results again
    with db_engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(SearchResult)
                         .where(SearchResult.url.like("https://%.example/%"))).scalar()
        last = conn.execute(select(func.max(SearchResult.last_seen_at))).scalar()
    assert n == 2 and last >= first


TRIMMED = {"groups": [{"key": "listing", "label": "listing", "items": []},
                      {"key": "front_bumper", "label": "part front_bumper — dent", "items": []},
                      {"key": "L7", "label": "tyre L7 front left — mid", "items": []}],
           "sources": {"S1": {"url": "https://c.example/1", "title": "Used Ertiga", "group": "listing"},
                       "S2": {"url": "https://c.example/2", "title": "Bumper", "group": "front_bumper"},
                       "S3": {"url": "https://c.example/3", "title": "Tyre", "group": "L7"}},
           "stats": {}}
FIGURES = {"kept": [
    {"source": "S1", "type": "single_listing", "price_text": ["₹ 9,95,000"], "about": "this_car", "year": 2022,
     "km": 30000, "variant": "ZXi", "group": "listing", "url": "https://c.example/1", "inr": [995000]},
    {"source": "S1", "type": "single_listing", "price_text": ["₹ 9,95,000"], "about": "this_car", "year": 2022,
     "group": "listing", "url": "https://c.example/1", "inr": [995000]},  # same listing twice in one answer
    {"source": "S2", "type": "part_price", "price_text": ["Rs 3,500", "Rs 4,000"], "group": "front_bumper",
     "url": "https://c.example/2", "inr": [3500, 4000]},
    {"source": "S3", "type": "tyre_price", "price_text": ["₹5,200"], "tyre_size": "185/65 R15", "group": "L7",
     "url": "https://c.example/3", "inr": [5200]}], "rejected": [], "outliers": []}


def test_figure_rows():
    rows = node_tables.figure_rows(FIGURES, TRIMMED, RECORD)
    assert [(r["figure_group"], r["part"]) for r in rows] == [("listing", None), ("part", "front_bumper"), ("tyre", "L7")]
    listing, part, tyre = rows
    assert (listing["year"], listing["km"], listing["variant_key"], listing["model_key"]) == (2022, 30000, "zxi", "ertiga")
    assert (listing["price_low_inr"], listing["price_high_inr"], listing["source_title"]) == (995000, 995000, "Used Ertiga")
    assert (part["price_low_inr"], part["price_high_inr"], part["year"]) == (3500, 4000, None)
    assert tyre["tyre_size"] == "185/65 R15" and tyre["city"] == "Pimpri-Chinchwad"


def test_price_figures_are_kept_and_only_dated_again(db_engine):
    from sqlalchemy import delete, func, select

    from app.models import PriceFigure

    with db_engine.begin() as conn:
        conn.execute(delete(PriceFigure).where(PriceFigure.source_url.like("https://c.example/%")))
    run_id = run_index.create_run_row(sha256="ad" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "04_confirm.json", RECORD)
    results.save_result(run_id, "08_extract/trimmed.json", TRIMMED)
    results.save_result(run_id, "08_extract/figures.json", FIGURES)
    results.save_result(run_id, "08_extract/figures.json", FIGURES)  # same figures again (re-run)
    with db_engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(PriceFigure)
                         .where(PriceFigure.source_url.like("https://c.example/%"))).scalar()
    assert n == 3
    results.delete_results(run_id, "extract")  # clearing the node keeps the cross-run figures
    with db_engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(PriceFigure)
                            .where(PriceFigure.source_url.like("https://c.example/%"))).scalar() == 3


PRICE = {"status": "ok", "new_price": {"value": 1334000, "type": "on_road", "variant_match": "exact"},
         "repairs": {"items": [], "total": 19087.5}, "listings_used": [{"source": "S1"}, {"source": "S2"}],
         "car_age_years": 3, "fair_value": {"median": 1074000, "max": 1086000},
         "after_repairs": {"median": 1060000, "max": 1071000}}


def test_price_row():
    assert node_tables.price_row(PRICE) == {
        "status": "ok", "low_inr": 1060000, "high_inr": 1071000, "new_price_inr": 1334000, "variant_match": "exact",
        "car_age_years": 3, "listings_used": 2, "repairs_total_inr": 19088, "reason": None}
    row = node_tables.price_row({"status": "unavailable", "reason": "no new-car price found", "repairs": {"total": 0}})
    assert (row["low_inr"], row["new_price_inr"], row["listings_used"]) == (None, None, 0)


def test_price_json_fills_prices_and_rerun_clears_it(db_engine):
    from sqlalchemy import select

    from app.models import Price

    run_id = run_index.create_run_row(sha256="ae" * 32, original_filename="x.mp4", size_bytes=1, duration_sec=1.0)
    results.save_result(run_id, "09_report/price.json", PRICE)
    results.save_result(run_id, "09_report/price.json", PRICE)  # saved again: still one row
    with db_engine.connect() as conn:
        rows = conn.execute(select(Price.low_inr, Price.high_inr).where(Price.run_id == run_id)).all()
    assert rows == [(1060000, 1071000)]
    results.delete_results(run_id, "pricing")
    with db_engine.connect() as conn:
        assert conn.execute(select(Price).where(Price.run_id == run_id)).first() is None
    assert results.load_result(run_id, "09_report/price.json") is None
