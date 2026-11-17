"""Step 8.2: the visitor's address behind CloudFront (auth.client_ip_header)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.auth_routes import client_ip


def test_header_wins_when_sent():
    assert client_ip("203.0.113.7", "172.18.0.4") == "203.0.113.7"


def test_first_address_of_a_list():
    assert client_ip(" 203.0.113.7 , 10.0.0.1", "172.18.0.4") == "203.0.113.7"


def test_peer_without_header():
    assert client_ip(None, "127.0.0.1") == "127.0.0.1"
    assert client_ip("  ", "127.0.0.1") == "127.0.0.1"
    assert client_ip(None, None) == "unknown"
