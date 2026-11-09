"""The sharded runner never trusts or writes to a server that is not its own cluster.

`pg_isready` only says that *something* accepts connections on a port. These tests start real
throwaway clusters (PostgreSQL 18 binaries, the same ones the runner uses; they do not touch the
`DATABASE_URL` server) and prove that identity is checked against this run's `pgdata` before any
`createdb`, and that a port collision is refused without writing to the server that answers there.
"""

import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.database

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_sharded_tests.py"
_spec = importlib.util.spec_from_file_location("run_sharded_tests", _PATH)
assert _spec is not None and _spec.loader is not None
runner = importlib.util.module_from_spec(_spec)
sys.modules["run_sharded_tests"] = runner
_spec.loader.exec_module(runner)


@pytest.fixture
def pg_bin() -> Path:
    return runner.find_pg_bin(None)  # fails (never skips) when PostgreSQL 18 binaries are missing


@pytest.fixture
def clusters(tmp_path: Path, pg_bin: Path) -> Iterator["list[runner.Shard]"]:
    started: list[runner.Shard] = []
    yield started
    for shard in started:
        runner.stop_cluster(shard, pg_bin)


def _start(
    tmp_path: Path,
    pg_bin: Path,
    started: "list[runner.Shard]",
    index: int,
    port: int,
    **kwargs: object,
) -> "runner.Shard":
    shard = runner.Shard(index=index, total=4, root=tmp_path / f"shard-{index}")
    started.append(shard)
    runner.start_cluster(shard, pg_bin, runner.KillOnCloseJob(platform="linux"), port, **kwargs)  # type: ignore[arg-type]
    return shard


def _databases(shard: "runner.Shard") -> set[str]:
    with psycopg.connect(
        host="127.0.0.1", port=shard.port, user="postgres", password=runner._DB_PASSWORD,
        dbname="postgres",
    ) as connection:  # fmt: skip
        return {row[0] for row in connection.execute("SELECT datname FROM pg_database")}


def test_the_runners_own_cluster_is_recognised_and_another_directory_is_not(
    tmp_path: Path, pg_bin: Path, clusters: "list[runner.Shard]"
) -> None:
    first = _start(tmp_path, pg_bin, clusters, 1, runner.free_ports(1)[0])
    assert runner._DB_NAME in _databases(first)
    assert first.server is not None
    runner.verify_server_identity(first.port, first.pgdata, first.server.pid)  # the real one: fine
    with pytest.raises(runner.ForeignServerError, match="serves"):
        runner.verify_server_identity(first.port, tmp_path / "somewhere-else", first.server.pid)
    with pytest.raises(runner.ForeignServerError, match="postmaster.pid"):
        runner.verify_server_identity(first.port, first.pgdata, first.server.pid + 1)


def test_a_port_collision_is_refused_without_writing_to_the_server_that_answers(
    tmp_path: Path, pg_bin: Path, clusters: "list[runner.Shard]"
) -> None:
    foreign = _start(tmp_path, pg_bin, clusters, 1, runner.free_ports(1)[0])
    before = _databases(foreign)

    # Only one attempt allowed: the collision is a hard, safe failure, and nothing was created.
    with pytest.raises(runner.ForeignServerError):
        _start(tmp_path, pg_bin, clusters, 2, foreign.port, db_name="dnd_ai_intruder", attempts=1)
    assert _databases(foreign) == before

    # With retries the run moves to another port and still never touches the foreign server.
    third = _start(tmp_path, pg_bin, clusters, 3, foreign.port, db_name="dnd_ai_intruder")
    assert third.port != foreign.port
    assert "dnd_ai_intruder" in _databases(third)
    assert _databases(foreign) == before


def test_a_collision_where_the_foreign_server_answers_first_is_caught_by_identity(
    tmp_path: Path, pg_bin: Path, clusters: "list[runner.Shard]", monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if the port looked free when probed, a foreign server that answers `pg_isready` before
    this run's own postmaster has exited is rejected by the identity check, before `createdb`."""
    foreign = _start(tmp_path, pg_bin, clusters, 1, runner.free_ports(1)[0])
    before = _databases(foreign)
    monkeypatch.setattr(runner, "port_in_use", lambda _port: False)  # the probe is fooled
    with pytest.raises(runner.ForeignServerError):
        _start(tmp_path, pg_bin, clusters, 2, foreign.port, db_name="dnd_ai_intruder", attempts=1)
    assert _databases(foreign) == before


def _run_plugin(
    tmp_path: Path, url_shard: "runner.Shard", pgdata: Path
) -> "subprocess.CompletedProcess[str]":
    isolation = tmp_path / "isolation"
    isolation.mkdir(exist_ok=True)
    (isolation / "default_config_plugin.py").write_text(runner._ISOLATION_PLUGIN)
    (tmp_path / "test_noop.py").write_text("def test_noop():\n    pass\n")
    environment = runner.shard_environment(url_shard, isolation)
    environment["RUNNER_SHARD_PGDATA"] = str(pgdata)
    return subprocess.run(  # noqa: S603
        [
            sys.executable, "-m", "pytest", "-p", "default_config_plugin", "-p", "no:cacheprovider",
            "-q", str(tmp_path / "test_noop.py"), f"--rootdir={tmp_path}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )  # fmt: skip


def test_the_session_plugin_refuses_a_database_that_is_not_this_runs_cluster(
    tmp_path: Path, pg_bin: Path, clusters: "list[runner.Shard]"
) -> None:
    mine = _start(tmp_path, pg_bin, clusters, 1, runner.free_ports(1)[0])
    other = _start(tmp_path, pg_bin, clusters, 2, runner.free_ports(1)[0])
    ok = _run_plugin(tmp_path, mine, mine.pgdata)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    # DATABASE_URL names `mine`, but this run says its cluster is `other`'s directory.
    refused = _run_plugin(tmp_path, mine, other.pgdata)
    assert refused.returncode != 0
    assert "not this run's cluster" in refused.stdout + refused.stderr
