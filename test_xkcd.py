"""Assert-based tests for xkcd.py. Run with `python3 test_xkcd.py`."""
import sys
import tempfile
import traceback
from pathlib import Path

import xkcd


def tmpdb():
    """A fresh initialised database inside a private temp directory."""
    d = tempfile.mkdtemp(prefix="xkcd-test-")
    db = xkcd.connect(Path(d) / "t.db")
    xkcd.init_db(db)
    return db


def test_init_db_creates_both_tables():
    db = tmpdb()
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert "comics" in names, names
    assert "comics_fts" in names, names


def test_connect_sets_row_factory():
    db = tmpdb()
    db.execute("INSERT INTO comics (num, title) VALUES (1, 'Barrel - Part 1')")
    row = db.execute("SELECT num, title FROM comics WHERE num = 1").fetchone()
    assert row["title"] == "Barrel - Part 1"


def test_fts5_roundtrip():
    db = tmpdb()
    db.execute(
        "INSERT INTO comics_fts (num, title, alt, transcript) "
        "VALUES (1, 'Gardening', 'I like gardens', '')"
    )
    got = db.execute(
        'SELECT num FROM comics_fts WHERE comics_fts MATCH \'"garden"\''
    ).fetchall()
    assert [r[0] for r in got] == [1]


def test_fts5_porter_stemming_matches_plurals():
    db = tmpdb()
    db.execute(
        "INSERT INTO comics_fts (num, title, alt, transcript) "
        "VALUES (7, 'Girlfriends', '', '')"
    )
    got = db.execute(
        'SELECT num FROM comics_fts WHERE comics_fts MATCH \'"girlfriend"\''
    ).fetchall()
    assert [r[0] for r in got] == [7]


def test_all_subcommands_parse():
    for argv in (["fetch"], ["analyze"], ["stats"], ["pack", "cats"], ["selftest"]):
        xkcd.build_parser().parse_args(argv)


def test_pack_requires_a_topic():
    try:
        xkcd.build_parser().parse_args(["pack"])
    except SystemExit as e:
        assert e.code == 2, e.code
    else:
        raise AssertionError("expected SystemExit(2) for `pack` with no topic")


def test_unknown_command_exits_2():
    try:
        xkcd.main(["definitely-not-a-command"])
    except SystemExit as e:
        assert e.code == 2, e.code
    else:
        raise AssertionError("expected SystemExit(2) for an unknown command")


def _run():
    tests = [
        (n, f)
        for n, f in sorted(globals().items())
        if n.startswith("test_") and callable(f)
    ]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception:
            bad += 1
            print(f"  FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_run())
