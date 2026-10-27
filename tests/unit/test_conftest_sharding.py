"""tests/conftest.py's CI shard selection (CI_TEST_SHARD).

CI runs the suite as parallel shards; a partition that dropped or duplicated
a file would silently skip verification or double-count it, so these prove
the shards are disjoint and together cover every file, and that a malformed
shard setting fails the run instead of running everything or nothing.
"""

from __future__ import annotations

import pytest

from tests.conftest import _parse_test_shard, _shard_files

pytestmark = pytest.mark.unit

FILES = [f"tests/database/test_{name:03d}.py" for name in range(23)] + [
    "tests/unit/test_a.py",
    "tests/scenario/test_b.py",
]


@pytest.mark.parametrize("total", [1, 2, 4, 7])
def test_shards_are_disjoint_and_cover_every_file(total: int) -> None:
    shards = [_shard_files(FILES, index, total) for index in range(1, total + 1)]
    assert set().union(*shards) == set(FILES)
    assert sum(len(shard) for shard in shards) == len(FILES)


def test_partition_ignores_collection_order_and_duplicates() -> None:
    reordered = list(reversed(FILES)) + FILES[:5]
    assert _shard_files(reordered, 2, 4) == _shard_files(FILES, 2, 4)


def test_adjacent_files_land_on_different_shards() -> None:
    ordered = sorted(FILES)
    first_four = [
        next(i for i in range(1, 5) if path in _shard_files(FILES, i, 4)) for path in ordered[:4]
    ]
    assert sorted(first_four) == [1, 2, 3, 4]


def test_a_valid_shard_setting_parses() -> None:
    assert _parse_test_shard(" 3/4 ") == (3, 4)


@pytest.mark.parametrize("value", ["", "3", "0/4", "5/4", "1/0", "a/b", "1/2/3", "-1/4"])
def test_a_malformed_shard_setting_is_a_usage_error(value: str) -> None:
    with pytest.raises(pytest.UsageError):
        _parse_test_shard(value)
