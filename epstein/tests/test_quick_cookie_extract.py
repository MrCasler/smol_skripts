"""Tests for quick_cookie_extract parsing logic (tab-separated and name=value)."""
import io
import json
import os
import sys
from pathlib import Path

import pytest

# Module under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_quick_extract_lines(lines):
    """Replicate quick_cookie_extract parsing; return list of cookie dicts (no file I/O)."""
    cookies = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 2:
                name, value = parts[0].strip(), parts[1].strip()
                if name.lower() in ("name", "cookie name", ""):
                    continue
                if name and value:
                    domain = ".justice.gov"
                    for i in range(2, min(5, len(parts))):
                        part = parts[i].strip()
                        if part and (part.startswith(".") or "justice.gov" in part):
                            domain = part if part.startswith(".") else "." + part.lstrip(".")
                            break
                    cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
        elif "=" in line:
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip()
            if name and value:
                cookies.append({"name": name, "value": value, "domain": ".justice.gov", "path": "/"})
    return cookies


def _run_quick_extract_stdin(lines, save_dir):
    """Run quick_cookie_extract.main() with stdin set to lines; save to save_dir."""
    from quick_cookie_extract import main
    old_stdin = sys.stdin
    sys.stdin = io.StringIO("\n".join(lines))
    try:
        old_cwd = os.getcwd()
        os.chdir(save_dir)
        try:
            main()
        finally:
            os.chdir(old_cwd)
    finally:
        sys.stdin = old_stdin


def test_parse_tab_separated_justice_cookies():
    """Tab-separated DevTools-style lines parse to cookie list."""
    lines = [
        "Name\tValue\tDomain\tPath",
        "ak_bmsc\tD233C68364FFEE97\t.justice.gov\t/",
        "_ga\tGA1.1.418891145.1770647709\t.justice.gov\t/",
    ]
    cookies = _parse_quick_extract_lines(lines)
    assert len(cookies) == 2
    names = [c["name"] for c in cookies]
    assert "ak_bmsc" in names
    assert "_ga" in names
    assert all(c.get("domain") == ".justice.gov" for c in cookies)


def test_parse_skips_header_row():
    """Header row 'Name' / 'Cookie name' is skipped."""
    lines = [
        "Cookie name\tValue",
        "sessionid\tabc123",
    ]
    cookies = _parse_quick_extract_lines(lines)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "sessionid"


def test_parse_name_value_format():
    """name=value lines are parsed."""
    lines = ["foo=bar", "baz=qux"]
    cookies = _parse_quick_extract_lines(lines)
    assert len(cookies) == 2
    assert {c["name"] for c in cookies} == {"foo", "baz"}


def test_quick_extract_writes_files_when_given_stdin(temp_dir):
    """When stdin has valid tab-separated cookies, main() writes cookies.json and cookies.txt."""
    lines = [
        "sessionid\tabc123",
    ]
    _run_quick_extract_stdin(lines, temp_dir)
    assert (temp_dir / "cookies.json").exists()
    assert (temp_dir / "cookies.txt").exists()
    data = json.loads((temp_dir / "cookies.json").read_text())
    assert len(data) == 1 and data[0]["name"] == "sessionid"
