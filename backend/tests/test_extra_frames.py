"""Extra frames per damage item (owner, 27 Nov 2026): locate's own moment + another angle; verify gets them all."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np

from app.frames import best_frame, locate_index, pick_angle_frame
from app.nodes.verify import item_frames


def test_locate_index_inside_the_video():
    assert locate_index(12.87, 30, 2000) == 386
    assert locate_index(-1, 30, 2000) == 0 and locate_index(999, 30, 2000) == 1999


def test_angle_frame_keeps_the_gap():
    scores = {100: 50.0, 105: 90.0, 110: 80.0, 120: 70.0, 130: 10.0}
    # taken 105 (sharpest) and 110 (locate); 30 fps, 0.5 s = 15 frames: 120 (10 from 110) is too close, 130 is far
    assert pick_angle_frame(scores, [105, 110], 30, 0.5) == 130
    assert pick_angle_frame(scores, [105, 110], 30, 0.1) == 120  # 0.1 s = 3 frames: sharpest far enough
    assert pick_angle_frame({100: 5.0, 101: 6.0}, [100, 101], 30, 0.5) is None


def test_best_frame_returns_every_score(tmp_path):
    video = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    rng = np.random.default_rng(1)
    for i in range(10):
        img = np.full((48, 64, 3), 128, np.uint8) if i != 6 else rng.integers(0, 255, (48, 64, 3), np.uint8)
        out.write(img)
    out.release()
    result = best_frame(video, list(range(10)), 0.5)
    assert set(result["scores"]) == set(range(10)) and result["frame_index"] == 6
    assert result["scores"][6] == max(result["scores"].values())


def _item(extra):
    return {"item_id": "L8", "category": "damage", "label": "scratch on bumper",
            "sharpest": {"file": "L8_damage_024.68s_sharp501.jpg"}, "extra": extra}


def test_verify_gets_all_frames_of_a_damage_once():
    frames = item_frames(_item([{"kind": "locate", "file": "L8_damage_024.70s_locate.jpg"},
                                {"kind": "angle", "file": "L8_damage_025.40s_angle.jpg"},
                                {"kind": "angle", "file": "L8_damage_024.70s_locate.jpg"}]))
    assert [f["file"] for f in frames] == ["L8_damage_024.68s_sharp501.jpg", "L8_damage_024.70s_locate.jpg",
                                           "L8_damage_025.40s_angle.jpg"]
    assert frames[0]["label"].endswith("(sharpest)") and frames[1]["label"].endswith("(the moment it was found)")
    assert {f["item_id"] for f in frames} == {"L8"}


def test_items_without_extra_frames_unchanged():
    frames = item_frames({"item_id": "L3", "category": "tyre", "label": "front tyre", "sharpest": {"file": "a.jpg"}})
    assert frames == [{"item_id": "L3", "category": "tyre", "label": "front tyre", "file": "a.jpg"}]
