"""The deadline report (tests/deadline_diagnostics.py) never raises, never masks the real failure, and survives any one
collector failing (R01 S5-E2 E10 correction, design section 10). The database-backed behaviour (a stalled request, a
gate that is never reached, the listener still registered at capture) is in tests/database/test_deadline_diagnostics.py."""

from pathlib import Path

import pytest

from tests import deadline_diagnostics as diagnostics

pytestmark = pytest.mark.unit


def test_a_collector_that_raises_is_reported_and_every_other_section_is_still_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNNER_DEADLINE_DIAG_DIR", str(tmp_path))

    def broken() -> str:
        raise RuntimeError("the thread collector is broken")

    monkeypatch.setattr(diagnostics, "_threads_section", broken)
    text, path = diagnostics.deadline_report("unit")
    assert path is not None and path.parent == tmp_path and path.read_text(encoding="utf-8") == text
    assert "collector failed: RuntimeError('the thread collector is broken')" in text
    for section in (
        "request completion and exception state",
        "database activity",
        "gate and listener state",
        "connection pool and checkout state",
        "asyncio tasks",
        "machine context",
    ):
        assert f"== {section}" in text, section


def test_an_unwritable_directory_still_returns_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv("RUNNER_DEADLINE_DIAG_DIR", str(blocker / "below"))
    text, path = diagnostics.deadline_report("unit")
    assert path is None and "report could not be written" in text
    assert "== machine context ==" in text


def test_the_message_never_raises_even_if_the_whole_report_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise MemoryError("worse than a collector")

    monkeypatch.setattr(diagnostics, "deadline_report", explode)
    message = diagnostics.deadline_message("unit")
    assert "deadline diagnostics unavailable" in message


def test_the_message_names_the_report_file_and_carries_the_start_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNNER_DEADLINE_DIAG_DIR", str(tmp_path))
    message = diagnostics.deadline_message("a gate was never reached")
    written = list(tmp_path.glob("*.txt"))
    assert len(written) == 1 and f"report file: {written[0]}" in message
    assert "DEADLINE DIAGNOSTICS: a gate was never reached" in message
