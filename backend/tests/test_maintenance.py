"""Step 9: maintenance-mode rules (docs/platform/09-cd.md §5a), without a database."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.maintenance import confirm_open, ready_to_restart

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def test_confirm_open_only_during_grace():
    assert confirm_open(False, None, NOW, 5)
    assert confirm_open(True, NOW - timedelta(minutes=4), NOW, 5)
    assert not confirm_open(True, NOW - timedelta(minutes=5), NOW, 5)
    assert not confirm_open(True, NOW - timedelta(seconds=1), NOW, 0)


def test_working_runs_block_the_restart():
    assert not ready_to_restart(1, 0, NOW - timedelta(hours=1), NOW, 5)


def test_runs_at_confirm_block_only_during_grace():
    assert not ready_to_restart(0, 2, NOW - timedelta(minutes=1), NOW, 5)
    assert ready_to_restart(0, 2, NOW - timedelta(minutes=6), NOW, 5)
    assert ready_to_restart(0, 0, NOW, NOW, 5)
