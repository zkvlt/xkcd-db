"""Assert-based tests for xkcd.py. Run with `python3 test_xkcd.py`."""
import json
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


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise xkcd.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_encode_image_url_percent_encodes_awkward_filenames():
    assert xkcd.encode_image_url(
        "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg"
    ) == "https://imgs.xkcd.com/comics/barrel_cropped_%281%29.jpg"
    assert xkcd.encode_image_url(
        "https://imgs.xkcd.com/comics/(.png"
    ) == "https://imgs.xkcd.com/comics/%28.png"


def test_encode_image_url_leaves_ordinary_filenames_alone():
    url = "https://imgs.xkcd.com/comics/fourier.jpg"
    assert xkcd.encode_image_url(url) == url


def test_image_filename_returns_the_original_name():
    assert xkcd.image_filename(
        "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg"
    ) == "barrel_cropped_(1).jpg"


def test_has_static_image_rejects_a_bare_directory_url():
    assert xkcd.has_static_image("https://imgs.xkcd.com/comics/") is False
    assert xkcd.has_static_image("https://imgs.xkcd.com/comics/throw.png") is True


def test_is_interactive_covers_all_three_detection_mechanisms():
    assert xkcd.is_interactive(1608, "https://imgs.xkcd.com/comics/") is True
    assert xkcd.is_interactive(1663, "https://imgs.xkcd.com/comics/") is True
    assert xkcd.is_interactive(2445, "https://imgs.xkcd.com/comics/checkbox.gif") is True
    assert xkcd.is_interactive(1525, "https://imgs.xkcd.com/comics/emojic_8_ball.png") is True
    assert xkcd.is_interactive(1, "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg") is False


def test_request_json_retries_then_succeeds():
    calls = {"n": 0}
    original = xkcd._get

    def flaky(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise xkcd.requests.ConnectionError("transient")
        return FakeResponse(200, {"num": 1})

    xkcd._get = flaky
    try:
        assert xkcd.request_json("https://example.test/x", backoff=0) == {"num": 1}
    finally:
        xkcd._get = original
    assert calls["n"] == 3


def test_request_json_returns_none_on_404():
    original = xkcd._get
    xkcd._get = lambda url, timeout: FakeResponse(404)
    try:
        assert xkcd.request_json("https://example.test/404") is None
    finally:
        xkcd._get = original


def test_request_json_raises_after_exhausting_attempts():
    original = xkcd._get
    xkcd._get = lambda url, timeout: FakeResponse(503)
    try:
        try:
            xkcd.request_json("https://example.test/x", attempts=2, backoff=0)
        except xkcd.requests.RequestException:
            pass
        else:
            raise AssertionError("expected a RequestException after all attempts")
    finally:
        xkcd._get = original


PAYLOAD_1 = {
    "num": 1,
    "title": "Barrel - Part 1",
    "safe_title": "Barrel - Part 1",
    "alt": "Don't we all.",
    "transcript": COMIC_1,
    "news": "",
    "link": "",
    "year": "2006",
    "month": "1",
    "day": "1",
    "img": "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg",
}


def test_upsert_comic_assembles_an_iso_date():
    db = tmpdb()
    xkcd.upsert_comic(db, PAYLOAD_1)
    row = db.execute("SELECT * FROM comics WHERE num = 1").fetchone()
    assert row["date"] == "2006-01-01"
    assert row["alt"] == "Don't we all."
    assert row["img_url"].endswith("barrel_cropped_(1).jpg")


def test_upsert_comic_pads_single_digit_months_and_days():
    db = tmpdb()
    payload = dict(PAYLOAD_1, year="2015", month="11", day="9")
    xkcd.upsert_comic(db, payload)
    assert db.execute("SELECT date FROM comics").fetchone()["date"] == "2015-11-09"


def test_upsert_comic_is_idempotent():
    db = tmpdb()
    xkcd.upsert_comic(db, PAYLOAD_1)
    xkcd.upsert_comic(db, PAYLOAD_1)
    assert db.execute("SELECT COUNT(*) c FROM comics").fetchone()["c"] == 1


def test_upsert_comic_ignores_unknown_keys():
    """#2198 ships an undocumented `extra_parts` key."""
    db = tmpdb()
    xkcd.upsert_comic(db, dict(PAYLOAD_1, extra_parts={"headerextra": "<style>"}))
    assert db.execute("SELECT COUNT(*) c FROM comics").fetchone()["c"] == 1


def test_image_dest_keeps_the_original_extension():
    dest = xkcd.image_dest(1, "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg")
    assert dest.name == "0001.jpg"


def test_needs_image_true_when_a_previous_download_failed():
    row = {"img_url": "https://imgs.xkcd.com/comics/throw.png", "img_path": None}
    assert xkcd.needs_image(row) is True


def test_needs_image_false_when_already_downloaded():
    row = {"img_url": "https://imgs.xkcd.com/comics/throw.png",
           "img_path": "data/comics/2198.png"}
    assert xkcd.needs_image(row) is False


def test_needs_image_false_when_the_comic_has_no_static_image():
    row = {"img_url": "https://imgs.xkcd.com/comics/", "img_path": None}
    assert xkcd.needs_image(row) is False


ROW_WITH_TRANSCRIPT = {
    "num": 1, "title": "Barrel - Part 1", "alt": "Don't we all.",
    "transcript": COMIC_1, "img_url": "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg",
}
ROW_WITHOUT_TRANSCRIPT = {
    "num": 2198, "title": "Throw", "alt": "this calculator implements...",
    "transcript": "", "img_url": "https://imgs.xkcd.com/comics/throw.png",
}


def test_analyze_row_computes_text_features():
    got = xkcd.analyze_row(ROW_WITH_TRANSCRIPT)
    assert got["scene_blocks"] == 2
    assert got["dialogue_lines"] == 1
    assert json.loads(got["speakers"]) == ["Boy"]
    assert got["has_transcript"] == 1
    assert got["title_len"] == len("Barrel - Part 1")
    assert got["alt_len"] == len("Don't we all.")


def test_analyze_row_nulls_every_text_field_without_a_transcript():
    """Review Focus 1: absent must not become zero."""
    got = xkcd.analyze_row(ROW_WITHOUT_TRANSCRIPT)
    assert got["has_transcript"] == 0
    assert got["scene_blocks"] is None
    assert got["dialogue_lines"] is None
    assert got["speakers"] is None
    assert got["title_len"] == len("Throw")


def test_analyze_row_zero_is_kept_when_a_transcript_has_no_scene_blocks():
    """#300 has a transcript whose only [[...]] is inline, so 0 is correct here."""
    row = dict(ROW_WITH_TRANSCRIPT, num=300, transcript=COMIC_300)
    got = xkcd.analyze_row(row)
    assert got["has_transcript"] == 1
    assert got["scene_blocks"] == 0


def test_analyze_row_marks_interactive_comics():
    row = dict(ROW_WITHOUT_TRANSCRIPT, num=1663,
               img_url="https://imgs.xkcd.com/comics/")
    assert xkcd.analyze_row(row)["is_interactive"] == 1
    assert xkcd.analyze_row(ROW_WITHOUT_TRANSCRIPT)["is_interactive"] == 0


def test_run_analyze_updates_rows_and_rebuilds_fts():
    db = tmpdb()
    xkcd.upsert_comic(db, PAYLOAD_1)
    xkcd.upsert_comic(db, dict(PAYLOAD_1, num=2, title="Tree", transcript="",
                               img="https://imgs.xkcd.com/comics/tree_cropped_(1).jpg"))
    assert xkcd.run_analyze(db) == 2

    assert db.execute("SELECT scene_blocks FROM comics WHERE num = 1").fetchone()[0] == 2
    assert db.execute("SELECT scene_blocks FROM comics WHERE num = 2").fetchone()[0] is None
    hits = db.execute(
        'SELECT num FROM comics_fts WHERE comics_fts MATCH \'"barrel"\''
    ).fetchall()
    assert [r[0] for r in hits] == [1]


def test_run_analyze_is_idempotent():
    """Re-running must not duplicate index rows, which DELETE-then-INSERT can do."""
    db = tmpdb()
    xkcd.upsert_comic(db, PAYLOAD_1)
    xkcd.run_analyze(db)
    first = dict(db.execute("SELECT * FROM comics WHERE num = 1").fetchone())
    xkcd.run_analyze(db)
    second = dict(db.execute("SELECT * FROM comics WHERE num = 1").fetchone())
    assert first == second
    assert db.execute("SELECT COUNT(*) c FROM comics_fts").fetchone()["c"] == 1


def seeded_db():
    """Three comics: one with a transcript, two without."""
    db = tmpdb()
    xkcd.upsert_comic(db, PAYLOAD_1)
    xkcd.upsert_comic(db, dict(PAYLOAD_1, num=2, title="Tree", transcript="",
                               alt="a tree",
                               img="https://imgs.xkcd.com/comics/tree_cropped_(1).jpg"))
    xkcd.upsert_comic(db, dict(PAYLOAD_1, num=3, title="Python", transcript="",
                               alt="I wrote 20 short programs in Python yesterday. It was wonderful.",
                               img="https://imgs.xkcd.com/comics/python.png"))
    xkcd.run_analyze(db)
    return db


def test_corpus_stats_counts_transcript_coverage():
    s = xkcd.corpus_stats(seeded_db())
    assert s["total"] == 3
    assert s["with_transcript"] == 1
    assert s["without_transcript"] == 2


def test_corpus_stats_scopes_transcript_metrics():
    """Transcript metrics must be labelled with their coverage, not corpus-wide."""
    s = xkcd.corpus_stats(seeded_db())
    assert s["scene_blocks_over"] == 1
    assert s["scene_blocks_median"] == 2
    assert s["non_transcript_rows"] == 2


def test_corpus_stats_top_speakers_ignores_transcript_less_rows():
    s = xkcd.corpus_stats(seeded_db())
    assert s["top_speakers"][0] == ("Boy", 1)


def test_corpus_stats_counts_topics_from_the_synonym_map():
    s = xkcd.corpus_stats(seeded_db())
    assert s["topic_counts"]["programming"] >= 1


def test_corpus_stats_reports_title_and_alt_lengths():
    s = xkcd.corpus_stats(seeded_db())
    assert s["title_len"]["max"] == len("Barrel - Part 1")
    assert s["alt_len"]["min"] == len("a tree")


def romance_db():
    """seeded_db plus a comic whose text says 'boyfriend' but never 'romance'."""
    db = seeded_db()
    xkcd.upsert_comic(db, dict(PAYLOAD_1, num=600, title="Android Boyfriend",
                               alt="Happy Valentine's Day!",
                               img="https://imgs.xkcd.com/comics/android_boyfriend.png"))
    xkcd.rebuild_fts(db)
    return db


def test_retrieve_matches_a_synonym_not_just_the_literal_word():
    """pack 'romance' must find a comic whose text says 'boyfriend', not 'romance'."""
    numbers = [r["num"] for r in xkcd.retrieve(romance_db(), "romance")]
    assert 600 in numbers


def test_retrieve_returns_relevant_comics_before_irrelevant_ones():
    db = seeded_db()
    numbers = [r["num"] for r in xkcd.retrieve(db, "programming")]
    assert numbers[0] == 3


def test_retrieve_returns_empty_for_an_unsatisfiable_topic():
    db = seeded_db()
    assert xkcd.retrieve(db, "ferrofluid ziggurat") == []


def test_retrieve_never_raises_on_hostile_topics():
    """Review Focus 2, end to end through the real query path."""
    db = seeded_db()
    for hostile in ["gardening AND", 'a "quote', "NEAR(", "a - b", "OR OR",
                    "garden)(", "NOT x", "*", "", "   "]:
        xkcd.retrieve(db, hostile)


def test_format_pack_includes_the_script_ready_fields():
    db = seeded_db()
    text = xkcd.format_pack(db, "barrel", xkcd.retrieve(db, "barrel"))
    assert "Title: Barrel - Part 1" in text
    assert "Alt: Don't we all." in text
    assert "[[A boy sits in a barrel" in text


def test_format_pack_says_so_when_nothing_matches():
    db = seeded_db()
    text = xkcd.format_pack(db, "ferrofluid ziggurat", [])
    assert "No comics matched" in text


def test_format_pack_reports_the_speaker_roster():
    db = seeded_db()
    text = xkcd.format_pack(db, "barrel", xkcd.retrieve(db, "barrel"))
    assert "Boy" in text


def test_run_selftest_fails_cleanly_on_an_empty_corpus():
    """It must report, not traceback, when the corpus has not been built yet."""
    assert xkcd.run_selftest(tmpdb()) == 1


def test_format_stats_handles_an_empty_corpus():
    """Critical: `stats` raised TypeError formatting a None percentile."""
    text = xkcd.format_stats(xkcd.corpus_stats(tmpdb()))
    assert "comics" in text
    assert "0" in text


def test_corpus_stats_percentiles_are_none_when_there_is_no_data():
    s = xkcd.corpus_stats(tmpdb())
    assert s["title_len"] == {"min": None, "median": None, "p90": None, "max": None}
    assert s["scene_blocks"]["median"] is None


def test_comic_numbers_limit_zero_means_nothing():
    """Important: `--limit 0` was falsy, so it started a full corpus fetch."""
    assert xkcd.comic_numbers(10, 0) == []
    assert xkcd.comic_numbers(10, None) == list(range(1, 11))
    assert xkcd.comic_numbers(10, 3) == [1, 2, 3]


def test_comic_numbers_skips_404():
    assert 404 not in xkcd.comic_numbers(405)
    assert xkcd.comic_numbers(405, 405) == [n for n in range(1, 406) if n != 404]


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
