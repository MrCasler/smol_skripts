"""Pytest fixtures for epstein tests."""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_netscape_cookies(temp_dir):
    """Path to a valid Netscape-format cookie file."""
    p = temp_dir / "cookies.txt"
    p.write_text(
        "# Netscape HTTP Cookie File\n"
        "# http://curl.haxx.se/rfc/cookie_spec.html\n"
        ".justice.gov\tTRUE\t/\tTRUE\t1786197988\t_ga\tGA1.1.990526474.1770645986\n"
        ".justice.gov\tTRUE\t/\tTRUE\t1786197988\tQueueITAccepted\tEventId%3Dusdojsearch\n"
    )
    return p


@pytest.fixture
def sample_json_cookies(temp_dir):
    """Path to a valid JSON cookie file."""
    p = temp_dir / "cookies.json"
    p.write_text("""[
        {"name": "_ga", "value": "GA1.1.418891145.1770647709", "domain": ".justice.gov", "path": "/"},
        {"name": "QueueITAccepted-SDFrts345E-V3_usdojsearch", "value": "EventId%3Dusdojsearch", "domain": ".justice.gov", "path": "/"}
    ]""")
    return p


@pytest.fixture
def sample_search_html():
    """Minimal HTML that the justice.gov search might return, with EFTA file IDs."""
    return """
    <html><body>
    <div class="results">
        <a href="/epstein/files/DataSet%208/EFTA00024813.pdf">EFTA00024813.pdf - DataSet 8</a>
        <span>No Images Produced EFTA00024813</span>
        <a href="/epstein/files/DataSet%208/EFTA00033177.pdf">EFTA00033177.pdf - DataSet 8</a>
        <span>No Images Produced EFTA00033177</span>
    </div>
    <a href="?page=2">Next</a>
    </body></html>
    """
