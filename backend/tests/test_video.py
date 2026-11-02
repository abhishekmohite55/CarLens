"""Tests for video.shrink_video."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.video import shrink_video, ffmpeg_exe


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
