"""Hardening A2 / A4: upload slots, body size, photo header checks (no database)."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.nodes import upload as upload_mod
from app.nodes.photos import header_problem, size_problem


def test_upload_slots():
    saved = upload_mod._receiving
    try:
        upload_mod._receiving = 0
        assert upload_mod.claim_upload_slot(2) and upload_mod.claim_upload_slot(2)
        assert not upload_mod.claim_upload_slot(2)
        upload_mod.release_upload_slot()
        assert upload_mod.claim_upload_slot(2)
    finally:
        upload_mod._receiving = saved


def test_body_too_large():
    mb = 1024 * 1024
    assert not upload_mod.body_too_large(str(500 * mb), 500)
    assert not upload_mod.body_too_large(None, 500)
    assert not upload_mod.body_too_large("not a number", 500)
    assert upload_mod.body_too_large(str(502 * mb), 500)


def test_size_problem():
    assert size_problem("JPEG", 4000, 3000, 50_000_000) is None
    assert "too large" in size_problem("PNG", 10000, 10000, 50_000_000)
    assert "Only JPEG" in size_problem("GIF", 10, 10, 50_000_000)


def _image_bytes(fmt: str, size=(64, 48)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format=fmt)
    return buf.getvalue()


def test_header_problem_reads_only_the_header():
    assert header_problem(_image_bytes("PNG"), 50_000_000) is None
    assert "too large" in header_problem(_image_bytes("PNG"), 1000)  # 64 x 48 = 3,072 pixels
    assert "Only JPEG" in header_problem(_image_bytes("GIF"), 50_000_000)
    assert "could not be read" in header_problem(b"not an image", 50_000_000)
