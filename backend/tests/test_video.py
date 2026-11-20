"""Tests for video.shrink_video."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.video import shrink_video


def test_shrink_video_calls_correct_command(tmp_path):
    src = tmp_path / "input.mp4"
    dst = tmp_path / "output.mp4"
    src.write_bytes(b"fake")

    with patch("app.video.ffmpeg_exe", return_value="ffmpeg"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = shrink_video(src, dst, height=1080, fps=5, crf=23)

    assert result == dst
    cmd = mock_run.call_args[0][0]
    assert "-vf" in cmd
    assert "scale=-2:1080" in cmd
    assert "-r" in cmd
    assert "5" in cmd
    assert "-crf" in cmd
    assert "23" in cmd
    assert "-an" in cmd


def test_shrink_video_raises_on_nonzero_exit(tmp_path):
    import subprocess
    src = tmp_path / "input.mp4"
    dst = tmp_path / "output.mp4"
    src.write_bytes(b"fake")

    with patch("app.video.ffmpeg_exe", return_value="ffmpeg"), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="bad codec")):
        with pytest.raises(RuntimeError):
            shrink_video(src, dst, height=1080, fps=5, crf=23)


def test_shrink_video_refuses_a_name_that_looks_like_an_option(tmp_path):  # hardening S1
    with patch("subprocess.run") as mock_run:
        with pytest.raises(RuntimeError):
            shrink_video(tmp_path / "-x.mp4", tmp_path / "out.mp4", height=480, fps=5, crf=30)
        with pytest.raises(RuntimeError):
            shrink_video(tmp_path / "in.mp4", tmp_path / "-y.mp4", height=480, fps=5, crf=30)
    mock_run.assert_not_called()


def test_shrink_video_passes_absolute_paths(tmp_path, monkeypatch):  # hardening S1
    monkeypatch.chdir(tmp_path)
    with patch("app.video.ffmpeg_exe", return_value="ffmpeg"), patch("subprocess.run") as mock_run:
        shrink_video(Path("in.mp4"), Path("out.mp4"), height=480, fps=5, crf=30)
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("-i") + 1] == str((tmp_path / "in.mp4").resolve())
    assert cmd[-1] == str((tmp_path / "out.mp4").resolve())


def test_shrink_video_timeout_raises(tmp_path):  # hardening A4
    import subprocess
    with patch("app.video.ffmpeg_exe", return_value="ffmpeg"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)) as run:
        with pytest.raises(RuntimeError, match="longer than 5 s"):
            shrink_video(tmp_path / "in.mp4", tmp_path / "out.mp4", height=480, fps=5, crf=30, timeout_sec=5)
    assert run.call_args.kwargs["timeout"] == 5
