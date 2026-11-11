"""The LF pin in .gitattributes covers exactly the frozen-manifest seed files."""

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _pinned() -> set[str]:
    pinned: set[str] = set()
    for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"database/seeds/(\S+)\s+(.*)", line.strip())
        if match and "eol=lf" in match.group(2).split():
            pinned.add(match.group(1))
    return pinned


def test_the_lf_pin_names_exactly_the_frozen_manifest_files() -> None:
    manifest = json.loads(
        (ROOT / "database/seeds/frozen_manifest.json").read_text(encoding="utf-8")
    )
    assert _pinned() == set(manifest["files"])


def test_no_wildcard_pins_the_whole_seed_directory() -> None:
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert not re.search(r"^database/seeds/\*", text, flags=re.MULTILINE)
