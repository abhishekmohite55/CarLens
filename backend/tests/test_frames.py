"""Tests for app/frames.py pure helpers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import cv2
import pytest

from app.frames import sample_indices, sharpness


def test_sample_indices_30fps_45_frames():
    # 30 fps, window=1.5 s, sample=15 fps → every 2nd source frame, 45 total
    indices = sample_indices(60.0, 30.0, 10000, 1.5, 15)
    assert len(indices) == 45
    assert indices[0] == round(58.5 * 30)  # first sample at t-1.5
    for i in range(1, len(indices)):
        assert indices[i] - indices[i - 1] == 2


def test_sample_indices_60fps_45_frames():
    # 60 fps → every 4th source frame, 45 total
    indices = sample_indices(60.0, 60.0, 20000, 1.5, 15)
    assert len(indices) == 45
    for i in range(1, len(indices)):
        assert indices[i] - indices[i - 1] == 4


def test_sample_indices_25fps_nearest():
    # 25 fps, nearest-frame mapping; all indices valid and unique
    indices = sample_indices(60.0, 25.0, 10000, 1.5, 15)
    assert len(indices) == len(set(indices))  # deduplication correct
    assert all(0 <= i < 10000 for i in indices)
    assert len(indices) <= 45


def test_sample_indices_clipped_near_start():
    # t=1.0 s: window starts at -0.5 s, indices below 0 dropped → fewer than 45
    indices = sample_indices(1.0, 30.0, 10000, 1.5, 15)
    assert all(i >= 0 for i in indices)
    assert len(indices) < 45


def test_sample_indices_clipped_near_end():
    # t near end of 100-frame video: indices beyond n_frames dropped
    n = 100
    indices = sample_indices(3.0, 30.0, n, 1.5, 15)
    assert all(i < n for i in indices)
    assert len(indices) < 45


def test_sharpness_blurred_less_than_sharp():
    # Sharp: alternating black/white rows → high Laplacian variance
    sharp_img = np.zeros((100, 100, 3), dtype=np.uint8)
    sharp_img[::2, :] = 255

    # Blurred: uniform grey → near-zero variance
    blur_img = np.full((100, 100, 3), 128, dtype=np.uint8)

    assert sharpness(sharp_img, 0.5) > sharpness(blur_img, 0.5)
