"""Check local Markdown destinations and the published API and table inventories.

Run from the repository root with the project environment. No database is opened.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from collections import Counter
from functools import cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dnd_ai.api.app import app
from dnd_ai.persistence.tables import metadata

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "docs" / "api"
CATALOGS = ("identity-and-access.md", "world-and-authoring.md", "play-and-integrations.md")


@cache
def prose(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    # Fenced commands and examples can contain Markdown-shaped data.
    return re.sub(r"^`{3}[^\n]*\n.*?^`{3}[ \t]*$", "", text, flags=re.MULTILINE | re.DOTALL)


@cache
def heading_ids(path: Path) -> set[str]:
    text = prose(path)
    result = set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', text))
    for title in re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE):
        title = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", title)
        title = re.sub(r"<[^>]+>", "", title).strip().lower()
        base = "".join(
            c for c in title if c in " -_" or unicodedata.category(c)[0] in "LMN"
        ).replace(" ", "-")
        slug = base
        suffix = 0
        while slug in result:
            suffix += 1
            slug = f"{base}-{suffix}"
        result.add(slug)
    return result


def check_links() -> list[str]:
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=ROOT,
    )
    problems = []
    for name in names.decode().strip("\0").split("\0"):
        source = ROOT / name
        if not source.is_file():
            continue  # An unstaged deletion still appears in the Git index.
        for match in re.finditer(r"\]\((<[^>\n]+>|(?:[^()\s]|\([^()\n]*\))+)\)", prose(source)):
            url = urlsplit(match[1].strip("<>"))
            if url.scheme or url.netloc:
                continue
            target = (source.parent / unquote(url.path)).resolve() if url.path else source
            if not target.exists() or (
                target.suffix == ".md"
                and url.fragment
                and unquote(url.fragment) not in heading_ids(target)
            ):
                problems.append(f"{name}: {match[1]}")
    return problems


def check_inventory() -> list[str]:
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    operations = {
        (method.upper(), path)
        for path, definition in app.openapi()["paths"].items()
        for method in definition
        if method in methods
    }
    documented = Counter(
        pair
        for filename in CATALOGS
        for pair in re.findall(r"^\| `([A-Z]+) (/[^ `]+)` \|", prose(API / filename), re.MULTILINE)
    )
    problems = [
        f"{method} {path}: expected {int((method, path) in operations)} row, found {documented[method, path]}"
        for method, path in sorted(operations | documented.keys())
        if documented[method, path] != int((method, path) in operations)
    ]
    index = prose(ROOT / "docs/reference/tables.md").split("## Design names absent", 1)[0]
    tables = set()
    for schema, row in re.findall(r"^### (\w+)\n\n([^\n]+)", index, re.MULTILINE):
        tables.update(f"{schema}.{name}" for name in re.findall(r"`(\w+)`", row))
    for table in sorted(tables.symmetric_difference(metadata.tables)):
        problems.append(f"Table inventory differs from metadata: {table}")
    return problems


if __name__ == "__main__":
    errors = check_links() + check_inventory()
    if errors:
        sys.exit("\n".join(errors))
    print("Local Markdown links, API operation coverage and declared table names agree.")
