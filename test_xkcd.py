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


# Real transcripts, copied from https://xkcd.com/<n>/info.0.json
COMIC_1 = (
    "[[A boy sits in a barrel which is floating in an ocean.]]\n"
    "Boy: I wonder where I'll float next?\n"
    "[[The barrel drifts into the distance. Nothing else can be seen.]]\n"
    "{{Alt: Don't we all.}}"
)

COMIC_300 = (
    "{{Title: Mildly sleazy uses of Facebook, part 14:}}\n"
    "{{subheading: Looking up someone's profile before introducing yourself}}\n"
    "Boy: Favorite bands? Hmm...\n"
    "Girl: Whoa, those are two of my favorites, too!\n"
    "Girl: Clearly, we should have sex.\n"
    "Boy: Okay!  My favorite position is the retrograde wheelbarrow.\n"
    "Girl: [[arms in the air]] Ohmygod, mine too!\n"
    "{{alt-text: 'Here, I'll put my number in your cell pho'}}"
)

# #487 excerpt. Note the bare `Title text:` on the first line, outside any braces.
COMIC_487 = (
    "Title text: XKCD presents a guide to numerical sex positions:\n"
    "69 \n"
    "[[traditional sixty-nine position, mutual oral sex]]\n"
    "99 \n"
    "[[sort of a standing doggy-style position]]\n"
    "34 \n"
    "Guy: Uh. \n"
    "[[guy and girl look confusedly at each other]]\n"
    "Narrator: Guys? \n"
    "{{title text: We didn't even get to the continued fractions!}}"
)


def test_scene_blocks_counts_line_standing_blocks():
    assert xkcd.scene_blocks(COMIC_1) == [
        "A boy sits in a barrel which is floating in an ocean.",
        "The barrel drifts into the distance. Nothing else can be seen.",
    ]


def test_scene_blocks_ignores_inline_stage_direction():
    # #300's only [[...]] sits mid-dialogue, so it is not a panel.
    assert xkcd.scene_blocks(COMIC_300) == []


def test_scene_blocks_on_excerpt_counts_only_standing_lines():
    assert len(xkcd.scene_blocks(COMIC_487)) == 3


def test_speakers_finds_real_speakers_in_order():
    assert xkcd.speakers(COMIC_1) == ["Boy"]
    assert xkcd.speakers(COMIC_300) == ["Boy", "Girl"]
    assert xkcd.speakers(COMIC_487) == ["Guy", "Narrator"]


def test_speakers_rejects_bare_metadata_label():
    # The bug this prevents: `Title text` becomes the corpus's 2nd common speaker.
    assert "Title text" not in xkcd.speakers(COMIC_487)


def test_speakers_keeps_caption_because_it_is_panel_content():
    assert xkcd.speakers("Caption: Meanwhile...") == ["Caption"]


def test_strip_metadata_removes_both_brace_forms():
    stripped = xkcd.strip_metadata(COMIC_300)
    assert "{{" not in stripped and "}}" not in stripped
    assert "((x))" not in xkcd.strip_metadata("((x)) Boy: hi")


def test_dialogue_lines_counts_speaker_lines_only():
    assert xkcd.dialogue_lines(COMIC_1) == 1
    assert xkcd.dialogue_lines(COMIC_300) == 5
    assert xkcd.dialogue_lines("") == 0


def test_empty_transcript_yields_empty_structures():
    assert xkcd.scene_blocks("") == []
    assert xkcd.speakers("") == []
    assert xkcd.dialogue_lines("") == 0


def test_expand_includes_the_topic_and_its_synonyms():
    got = xkcd.expand("romance")
    assert "romance" in got
    assert "girlfriend" in got
    assert "wedding" in got


def test_expand_is_sorted_and_deduplicated():
    assert xkcd.expand("cats") == ["cat", "cats", "feline", "kitten"]


def test_expand_normalises_case_and_whitespace():
    assert xkcd.expand("  Cats ") == ["cat", "cats", "feline", "kitten"]


def test_expand_unknown_topic_returns_only_itself():
    assert xkcd.expand("ferrofluid") == ["ferrofluid"]


def test_fts_query_quotes_every_word():
    assert xkcd.fts_query("a - b") == '"a" "b"'
    assert xkcd.fts_query("NEAR(") == '"near"'


def test_fts_query_returns_none_when_there_is_nothing_to_search():
    assert xkcd.fts_query("") is None
    assert xkcd.fts_query("   ") is None
    assert xkcd.fts_query("*") is None


def test_fts_query_never_raises_on_metacharacters():
    """Measured: these all raise sqlite3.OperationalError against raw MATCH."""
    db = tmpdb()
    db.execute(
        "INSERT INTO comics_fts (num, title, alt, transcript) VALUES (1, 'Garden', '', '')"
    )
    for hostile in [
        "gardening AND", 'a "quote', "NEAR(", "a - b", "OR OR",
        "garden)(", "NOT x", "*", "", "   ",
    ]:
        query = xkcd.fts_query(hostile)
        if query is None:
            continue
        db.execute(
            "SELECT num FROM comics_fts WHERE comics_fts MATCH ? LIMIT 5",
            (query,),
        ).fetchall()


def test_fts_query_expands_synonyms_into_a_disjunction():
    query = xkcd.fts_query("romance")
    assert " OR " in query
    assert '"girlfriend"' in query


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
