# xkcd Corpus and Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local SQLite corpus of every xkcd comic, analyse its text, and expose a pi skill that writes new xkcd-style comic scripts on any topic.

**Architecture:** One `xkcd.py` CLI with five subcommands. `fetch` writes raw API metadata into a `comics` table and images into `data/comics/`. `analyze` computes derived text fields in place, leaving them null where there is no transcript. `stats` reports aggregates. `pack` builds a retrieved-evidence block for a topic. `selftest` asserts against the live database. A pi skill reads `pack` output plus a written style guide and produces the script.

**Tech Stack:** Python 3.12, stdlib `argparse`/`sqlite3`/`re`/`json`, SQLite FTS5 with the porter tokenizer, `requests` for HTTP, Pillow for image dimensions. No test framework: `test_xkcd.py` is assert-based with a small runner.

**Spec:** `docs/superpowers/specs/2026-09-24-xkcd-db-design.md`

## Global Constraints

- Python 3.12. Standard library first.
- SQLite with FTS5. No ORM. `tokenize='porter unicode61'`.
- Permitted third-party imports: `requests` and `PIL` only, both already installed (`requests`, Pillow 11.1.0). No new dependencies, ever, for this project.
- No API keys. The corpus pipeline uses only public xkcd endpoints. The writer uses the pi session model.
- No embeddings, no vector store.
- Sequential HTTP with a delay between requests. No parallelism, no thread pools, in shipped code.
- Images write to `<path>.part` then rename. A partial file must never look complete.
- Exit codes: `0` success, `1` completed with recorded failures, `2` hard error or bad usage.
- `data/` is gitignored. The corpus is reproducible build output.
- Derived text fields are `NULL`, never `0`, when a comic has no transcript.
- Transcript-derived statistics are scoped to the 1665 comics that have one, and say so in the output.
- Writer output format is exactly `Title:` line, `Alt:` line, blank line, then `[[scene]]` and `Speaker: line` blocks.

## Corpus Facts These Tasks Assume

All measured across 3301 comics during planning. Do not re-derive; assert against them.

| Fact | Value |
| --- | --- |
| Comics that exist | 3301 (`#404` absent), latest `#3302` |
| With a transcript | 1665. Last one is `#1677` |
| Without a transcript | 1636 |
| Transcripts with no line-standing scene block | 207 |
| With alt text | 3298 (empty on `#1193`, `#1506`, `#1525`) |
| Alt length median / p90 / max | 115 / 209 / 816 |
| Title length median / p90 / max | 13 / 22 / 53 |
| No static image | `#1608`, `#1663` (bare directory URL, HTTP 403) |
| Animated `.gif` | `#961`, `#1116`, `#1264`, `#2293`, `#2445` |
| JS-driven with a static PNG | `#1110`, `#1416`, `#1525` |
| Filenames needing percent encoding | `#1`, `#2`, `#4`, `#7`, `#859` |

## Review Focus

Five input classes the spec implies but no single task's happy-path tests cover. Each has a test in the task that owns the code.

1. **A comic with no transcript (1636 of 3301).** A reasonable person expects its derived text fields to be absent rather than zero, so averages over the corpus are not dragged toward zero. Owned by Task 6.
2. **A topic string full of FTS5 metacharacters.** A reasonable person expects `pack 'a - b'` to return a result or a clean message, never a traceback. Measured: eight such inputs raise `OperationalError` if handed to `MATCH` raw. Owned by Task 3 and Task 8.
3. **A comic with no downloadable image (`#1608`, `#1663`) or an animated one (five `.gif`s).** A reasonable person expects these flagged rather than logged as download failures. Owned by Task 4.
4. **Filenames with parentheses or a leading `(` (`#859` is literally `(.png`).** A reasonable person expects the image on disk to have its original name, not a mangled one. Owned by Task 4.
5. **A fetch interrupted mid-run.** A reasonable person expects a rerun to complete what is missing without duplicating rows, mangling images, or counting a partial file as done. Owned by Task 5.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `xkcd.py` | Everything: schema, HTTP, parsing, analysis, retrieval, CLI dispatch |
| `test_xkcd.py` | Assert-based tests, no network, runnable as `python3 test_xkcd.py` |
| `.agents/skills/xkcd-write/SKILL.md` | The writer skill |
| `.agents/skills/xkcd-write/references/style-guide.md` | Distilled xkcd conventions |
| `docs/superpowers/specs/2026-09-24-xkcd-db-design.md` | The approved spec |

The spec fixes this as a single CLI rather than a package. At five subcommands a module split buys import plumbing, not clarity. If `xkcd.py` passes roughly 800 lines, revisit that decision.

---

### Task 1: CLI skeleton, schema, and FTS5 index

**Files:**
- Create: `xkcd.py`
- Create: `test_xkcd.py`

**Interfaces:**
- Consumes: nothing
- Produces: `xkcd.DB_PATH`, `xkcd.DATA_DIR`, `xkcd.COMICS_DIR`, `xkcd.connect(path=DB_PATH) -> sqlite3.Connection` (with `row_factory = sqlite3.Row`), `xkcd.init_db(db) -> None`, `xkcd.build_parser() -> argparse.ArgumentParser`, `xkcd.main(argv=None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
"""Assert-based tests for xkcd.py. Run with `python3 test_xkcd.py`."""
import sqlite3
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
    db.execute(
        "INSERT INTO comics (num, title) VALUES (1, 'Barrel - Part 1')"
    )
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: fails at import with `ModuleNotFoundError: No module named 'xkcd'`.

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""xkcd corpus tool. Fetches every comic, analyses the text, and serves evidence
for the xkcd-write skill.

Subcommands: fetch, analyze, stats, pack, selftest.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
COMICS_DIR = DATA_DIR / "comics"
DB_PATH = DATA_DIR / "xkcd.db"

LATEST_URL = "https://xkcd.com/info.0.json"
INFO_URL = "https://xkcd.com/{num}/info.0.json"
USER_AGENT = "xkcd-corpus/1.0 (personal archive; contact: local user)"

# Comic numbers that are JavaScript-driven but ship an ordinary static PNG, so
# no image inspection can detect them. See the spec's known special cases.
INTERACTIVE_NUMBERS = frozenset({1110, 1416, 1525})

SCHEMA = """
CREATE TABLE IF NOT EXISTS comics (
    num             INTEGER PRIMARY KEY,
    title           TEXT    NOT NULL DEFAULT '',
    safe_title      TEXT    NOT NULL DEFAULT '',
    alt             TEXT    NOT NULL DEFAULT '',
    transcript      TEXT    NOT NULL DEFAULT '',
    news            TEXT    NOT NULL DEFAULT '',
    link            TEXT    NOT NULL DEFAULT '',
    date            TEXT    NOT NULL DEFAULT '',
    img_url         TEXT    NOT NULL DEFAULT '',
    img_path        TEXT,
    img_bytes       INTEGER,
    img_width       INTEGER,
    img_height      INTEGER,
    fetched_at      TEXT,
    scene_blocks    INTEGER,
    dialogue_lines  INTEGER,
    speakers        TEXT,
    has_transcript  INTEGER,
    is_interactive  INTEGER,
    title_len       INTEGER,
    alt_len         INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS comics_fts USING fts5(
    num UNINDEXED,
    title,
    alt,
    transcript,
    tokenize='porter unicode61'
);
"""


def connect(path=DB_PATH):
    """Open the database, creating its parent directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def init_db(db):
    """Create the schema if it is not already present."""
    db.executescript(SCHEMA)
    db.commit()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="xkcd.py", description="xkcd corpus tool and writer support."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download comic metadata and images")
    fetch.add_argument("--limit", type=int, default=None,
                       help="stop after this many comics (for testing)")
    fetch.add_argument("--delay", type=float, default=0.15,
                       help="seconds to wait between requests")

    sub.add_parser("analyze", help="compute derived text fields")

    stats = sub.add_parser("stats", help="print corpus statistics")
    stats.add_argument("--top", type=int, default=15,
                       help="rows to show in ranked lists")

    pack = sub.add_parser("pack", help="build an evidence pack for a topic")
    pack.add_argument("topic")
    pack.add_argument("--n", type=int, default=8, help="exemplars to include")

    sub.add_parser("selftest", help="assert against the live database")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handler = globals().get("cmd_" + args.command)
    if handler is None:
        print(f"error: '{args.command}' is not implemented", file=sys.stderr)
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `7/7 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(db): add CLI skeleton, comics schema, and FTS5 index"
```

---

### Task 2: Transcript parsing

**Files:**
- Modify: `xkcd.py` (append after `init_db`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: nothing
- Produces: `xkcd.strip_metadata(text) -> str`, `xkcd.scene_blocks(text) -> list[str]`, `xkcd.speakers(text) -> list[str]`, `xkcd.dialogue_lines(text) -> int`

- [ ] **Step 1: Write the failing tests**

Fixtures are copied from the live API, not invented.

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures with `AttributeError: module 'xkcd' has no attribute 'scene_blocks'`.

- [ ] **Step 3: Write the implementation**

```python
SCENE_RE = re.compile(r"\[\[(.*?)\]\]", re.S)
META_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
NOTE_RE = re.compile(r"\(\((.*?)\)\)", re.S)
SPEAKER_RE = re.compile(r"(?m)^[ \t]*([A-Z][\w'\u2019 \-]{0,30}?)[ \t]*:[ \t]")

# Metadata labels that sit in transcripts and look exactly like dialogue.
# `Caption` is deliberately absent: a caption drawn inside a panel is content.
META_LABELS = re.compile(
    r"^(?:title|alt|mouseover|rollover|subtitle|subheading|headline|legend"
    r"|panel title|citation|footnote|author'?s comment|options|tag|medium)\b",
    re.I,
)


def strip_metadata(transcript):
    """Remove {{...}} and ((...)) blocks, which are metadata rather than dialogue."""
    return NOTE_RE.sub("", META_RE.sub("", transcript or ""))


def scene_blocks(transcript):
    """Line-standing [[...]] blocks. An inline [[...]] is a stage direction.

    Measured: 207 of 1665 transcripts have no standing block, 187 of them
    because they contain no [[...]] at all.
    """
    transcript = transcript or ""
    out = []
    for match in SCENE_RE.finditer(transcript):
        line_start = transcript.rfind("\n", 0, match.start()) + 1
        line_end = transcript.find("\n", match.end())
        if line_end == -1:
            line_end = len(transcript)
        before = transcript[line_start:match.start()].strip()
        after = transcript[match.end():line_end].strip()
        if not before and not after:
            out.append(match.group(1).strip())
    return out


def speakers(transcript):
    """Speaker names in first-appearance order, with metadata labels rejected."""
    seen = []
    for match in SPEAKER_RE.finditer(strip_metadata(transcript)):
        name = match.group(1).strip()
        if META_LABELS.match(name):
            continue
        if name not in seen:
            seen.append(name)
    return seen


def dialogue_lines(transcript):
    """How many Speaker: lines the transcript contains."""
    return len(SPEAKER_RE.findall(strip_metadata(transcript)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `16/16 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(parse): extract scene blocks and speakers from transcripts"
```

---

### Task 3: Synonym expansion and FTS5 query escaping

**Files:**
- Modify: `xkcd.py` (append after `dialogue_lines`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: nothing
- Produces: `xkcd.SYNONYMS: dict[str, list[str]]`, `xkcd.expand(topic) -> list[str]`, `xkcd.fts_query(topic) -> str | None`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures with `AttributeError: module 'xkcd' has no attribute 'expand'`.

- [ ] **Step 3: Write the implementation**

```python
# Broad subjects mapped to the words the corpus actually uses. Nothing is stored,
# so extending this needs no re-analysis.
SYNONYMS = {
    "math": ["math", "maths", "equation", "theorem", "proof", "integral",
             "derivative", "prime number", "geometry", "algebra", "fourier",
             "infinity"],
    "physics": ["physics", "physicist", "quantum", "relativity", "thermodynamics",
                "momentum", "friction", "entropy", "particle"],
    "space": ["spacecraft", "orbit", "nasa", "astronaut", "spaceship", "planet",
              "galaxy", "telescope", "rocket"],
    "biology": ["biology", "evolution", "genome", "dna", "species", "neuron",
                "organism", "photosynthesis"],
    "chemistry": ["chemistry", "chemical", "molecule", "atom", "periodic table",
                  "acid"],
    "programming": ["programming", "compile", "codebase", "refactor", "debug",
                    "python", "perl", "regex", "source code"],
    "computers": ["computer", "laptop", "hard drive", "keyboard", "browser",
                  "database", "encryption", "password", "operating system"],
    "ai": ["artificial intelligence", "machine learning", "neural network",
           "chatgpt", "robot"],
    "statistics": ["statistics", "statistical", "probability", "regression",
                   "correlation", "sample size", "standard deviation"],
    "engineering": ["engineer", "bridge", "gearbox", "circuit", "voltage",
                    "turbine", "welding"],
    "linguistics": ["linguistics", "grammar", "pronounce", "pronunciation",
                    "spelling", "dictionary", "vowel", "syntax", "etymology"],
    "philosophy": ["philosophy", "philosophical", "epistemology", "metaphysics",
                   "consciousness", "thought experiment", "solipsism"],
    "economics": ["economics", "economic", "inflation", "stock market", "taxes",
                  "bitcoin", "cryptocurrency", "recession"],
    "romance": ["girlfriend", "boyfriend", "dating", "romance", "romantic",
                "married", "marriage", "wedding", "kiss", "breakup", "crush"],
    "sex": ["sex", "sexual", "porn", "orgasm", "condom", "naked"],
    "existential": ["existential", "meaningless", "mortality", "mortal", "dying",
                    "death", "dead", "nihilism", "purpose of life"],
    "time-travel": ["time travel", "time machine", "paradox", "temporal",
                    "past self"],
    "internet": ["the internet", "website", "email", "wifi", "download", "online"],
    "social-media": ["facebook", "twitter", "tumblr", "instagram", "reddit",
                     "youtube", "social media", "blog"],
    "meta": ["webcomic", "this comic", "xkcd", "alt text", "comic strip"],
    "history": ["history", "historical", "century", "medieval", "roman empire",
                "world war"],
    "maps": ["map", "maps", "geography", "continent", "globe"],
    "food": ["food", "restaurant", "cooking", "recipe", "pizza", "coffee", "beer",
             "breakfast", "sandwich"],
    "health": ["doctor", "hospital", "medicine", "medical", "sleep", "exercise",
               "disease", "cancer", "vitamin"],
    "cats": ["cat", "kitten", "feline"],
    "parenting": ["toddler", "parenting", "my son", "my daughter", "my kids",
                  "baby"],
    "work": ["boss", "meeting", "office", "coworker", "deadline", "salary",
             "job interview"],
    "politics": ["politics", "political", "senator", "president", "election",
                 "congress", "voting"],
    "climate": ["climate", "global warming", "greenhouse", "emissions", "carbon"],
    "weather": ["weather", "tornado", "hurricane", "snowstorm", "thunderstorm"],
    "gardening": ["garden", "gardening", "lawn", "soil", "seed", "plant"],
}

WORD_RE = re.compile(r"\w+", re.UNICODE)


def expand(topic):
    """A topic plus its synonyms, lowercased, stripped, sorted, deduplicated."""
    base = (topic or "").strip().lower()
    if not base:
        return []
    return sorted({base} | set(SYNONYMS.get(base, ())))


def fts_query(topic):
    """A safe FTS5 MATCH expression for a topic, or None if nothing is searchable.

    Mandatory, not defensive. Measured against a live index: `gardening AND`,
    `a "quote`, `NEAR(`, `a - b`, `OR OR`, `garden)(`, `NOT x`, and an empty
    string all raise sqlite3.OperationalError when passed to MATCH directly.
    Tokenising to \\w+ and quoting every word removes every operator.
    """
    clauses = []
    for term in expand(topic):
        words = WORD_RE.findall(term)
        if words:
            # Quoted words separated by spaces are an implicit AND in FTS5.
            clauses.append(" ".join(f'"{w}"' for w in words))
    return " OR ".join(clauses) or None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `24/24 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(search): add synonym expansion and FTS5 query escaping"
```

---

### Task 4: Fetch internals, URL encoding, retry, and interactive rules

**Files:**
- Modify: `xkcd.py` (append after `fts_query`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: nothing
- Produces: `xkcd._get(url, timeout)`, `xkcd.request_json(url, attempts=3, backoff=1.0, timeout=30) -> dict | None`, `xkcd.image_filename(url) -> str`, `xkcd.encode_image_url(url) -> str`, `xkcd.has_static_image(url) -> bool`, `xkcd.is_interactive(num, img_url) -> bool`, `xkcd.download_image(url, dest) -> tuple[int, int, int] | None`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on `xkcd.encode_image_url` and `xkcd.request_json`.

- [ ] **Step 3: Write the implementation**

```python
import io
import time
import urllib.parse

import requests
from PIL import Image

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _get(url, timeout):
    """Single seam for HTTP so tests can replace it without a network."""
    return requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})


def request_json(url, attempts=3, backoff=1.0, timeout=30):
    """GET a URL and parse JSON, retrying transient failures.

    Returns None when the server answers 404, which for info.0.json means the
    comic does not exist. Raises after exhausting attempts.
    """
    last = None
    for attempt in range(attempts):
        try:
            response = _get(url, timeout)
            if response.status_code == 404:
                return None
            if response.status_code in RETRY_STATUS:
                raise requests.HTTPError(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(backoff * (2**attempt))
    raise last


def image_filename(url):
    """The image's original filename, exactly as xkcd spells it."""
    return (url or "").rsplit("/", 1)[-1]


def encode_image_url(url):
    """Percent-encode only the filename.

    Measured cases: `barrel_cropped_(1).jpg` -> `barrel_cropped_%281%29.jpg`, and
    `#859`'s `(.png` -> `%28.png`.
    """
    head, _, name = (url or "").rpartition("/")
    if not head:
        return urllib.parse.quote(url or "")
    return head + "/" + urllib.parse.quote(name)


def has_static_image(img_url):
    """False for the two comics whose img is a bare directory URL (#1608, #1663)."""
    return bool(image_filename(img_url).strip())


def is_interactive(num, img_url):
    """True when the comic has no static image, ships animation, or is JS-driven."""
    if not has_static_image(img_url):
        return True
    if image_filename(img_url).lower().endswith(".gif"):
        return True
    return num in INTERACTIVE_NUMBERS


def download_image(url, dest):
    """Download to <dest>.part, verify it parses, then rename. Returns
    (bytes, width, height), or None when the image is empty."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    response = _get(encode_image_url(url), 60)
    response.raise_for_status()
    if not response.content:
        part.unlink(missing_ok=True)
        return None
    with Image.open(io.BytesIO(response.content)) as image:
        width, height = image.size
    part.write_bytes(response.content)
    part.replace(dest)
    return len(response.content), width, height
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `32/32 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(fetch): add retrying HTTP, URL encoding, and interactive detection"
```

---

### Task 5: The `fetch` command

**Files:**
- Modify: `xkcd.py` (append after `download_image`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `connect`, `init_db`, `request_json`, `download_image`, `has_static_image`, `INFO_URL`, `LATEST_URL`
- Produces: `xkcd.upsert_comic(db, payload) -> None`, `xkcd.needs_image(row) -> bool`, `xkcd.cmd_fetch(args) -> int`, `xkcd.image_dest(num, url) -> Path`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on `xkcd.upsert_comic`.

- [ ] **Step 3: Write the implementation**

```python
RAW_FIELDS = ("num", "title", "safe_title", "alt", "transcript", "news", "link")


def _iso_date(payload):
    """xkcd returns month and day unpadded. Produce YYYY-MM-DD."""
    year = str(payload.get("year") or "").strip()
    month = str(payload.get("month") or "").strip()
    day = str(payload.get("day") or "").strip()
    if not (year and month and day):
        return ""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def upsert_comic(db, payload):
    """Insert or refresh one comic's raw fields. Idempotent.

    Unknown keys are ignored rather than rejected; #2198 ships an undocumented
    `extra_parts` key.
    """
    values = {field: (payload.get(field) or "") for field in RAW_FIELDS}
    values["date"] = _iso_date(payload)
    values["img_url"] = payload.get("img") or ""
    db.execute(
        """
        INSERT INTO comics (num, title, safe_title, alt, transcript, news, link,
                            date, img_url, fetched_at)
        VALUES (:num, :title, :safe_title, :alt, :transcript, :news, :link,
                :date, :img_url, :fetched_at)
        ON CONFLICT(num) DO UPDATE SET
            title = excluded.title,
            safe_title = excluded.safe_title,
            alt = excluded.alt,
            transcript = excluded.transcript,
            news = excluded.news,
            link = excluded.link,
            date = excluded.date,
            img_url = excluded.img_url,
            fetched_at = excluded.fetched_at
        """,
        {**values, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
    )
    db.commit()


def image_dest(num, img_url):
    """data/comics/0001.jpg, or None when the comic has no static image."""
    name = image_filename(img_url).strip()
    if not name:
        return None
    return COMICS_DIR / f"{num:04d}{Path(name).suffix.lower() or '.png'}"


def needs_image(row):
    """True when an image is expected but not yet on disk.

    Distinguishes 'never had one' from 'download failed' without needing a status
    column: a bare directory URL means none was ever expected.
    """
    if row["img_path"]:
        return False
    return has_static_image(row["img_url"])


def cmd_fetch(args):
    db = connect()
    init_db(db)

    latest = request_json(LATEST_URL)
    if latest is None:
        print("error: could not read the latest comic number", file=sys.stderr)
        return 2

    numbers = [n for n in range(1, latest["num"] + 1) if n != 404]
    if args.limit:
        numbers = numbers[: args.limit]

    fetched = skipped = failed = 0
    failures = []

    for index, num in enumerate(numbers, 1):
        existing = db.execute(
            "SELECT img_url, img_path FROM comics WHERE num = ?", (num,)
        ).fetchone()

        if existing is not None and not needs_image(existing):
            skipped += 1
            continue

        payload = request_json(INFO_URL.format(num=num))
        if payload is None:
            failures.append((num, "no metadata"))
            failed += 1
            continue

        upsert_comic(db, payload)
        fetched += 1

        img_url = payload.get("img") or ""
        dest = image_dest(num, img_url)
        if dest is not None:
            try:
                downloaded = download_image(img_url, dest)
            except Exception as exc:
                downloaded = None
                failures.append((num, f"image: {type(exc).__name__}"))
            if downloaded is None:
                if not any(f[0] == num for f in failures):
                    failures.append((num, "empty image"))
            else:
                size, width, height = downloaded
                db.execute(
                    "UPDATE comics SET img_path = ?, img_bytes = ?, img_width = ?,"
                    " img_height = ? WHERE num = ?",
                    (str(dest.relative_to(ROOT)), size, width, height, num),
                )
                db.commit()

        if index % 100 == 0:
            print(f"  {index}/{len(numbers)}  new={fetched} skipped={skipped}")

        time.sleep(args.delay)

    print(f"\nfetched {fetched}, skipped {skipped}, failed {len(failures)}")
    for num, why in failures[:40]:
        print(f"  #{num}: {why}")
    if failures:
        print(f"  ... {len(failures)} total failures")
    return 1 if failures else 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `40/40 passed`

- [ ] **Step 5: Verify against the live API on a small slice**

Run:

```bash
python3 xkcd.py fetch --limit 8 --delay 0.1
```

Expected: `fetched 8, skipped 0, failed 0`, exit code 0, and:

```bash
ls data/comics/
```

Expected: `0001.jpg 0002.jpg 0003.jpg 0004.jpg 0005.jpg 0006.jpg 0007.jpg 0008.jpg`

Then confirm the awkward filename survived:

```bash
python3 -c "import xkcd,sqlite3;d=xkcd.connect();print(d.execute('SELECT num,img_path FROM comics ORDER BY num LIMIT 4').fetchall()[0]['img_path'])"
```

Expected: `data/comics/0001.jpg`

Then confirm resume works, which is Review Focus item 5:

```bash
python3 xkcd.py fetch --limit 8 --delay 0.1; echo "exit=$?"
```

Expected: `fetched 0, skipped 8, failed 0` and `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(fetch): add resumable fetch command with failure reporting"
```

---

### Task 6: The `analyze` command

**Files:**
- Modify: `xkcd.py` (append after `cmd_fetch`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `connect`, `init_db`, `strip_metadata`, `scene_blocks`, `speakers`, `dialogue_lines`, `has_static_image`, `is_interactive`
- Produces: `xkcd.analyze_row(row) -> dict`, `xkcd.rebuild_fts(db) -> None`, `xkcd.run_analyze(db) -> int`, `xkcd.cmd_analyze(args) -> int`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on `xkcd.analyze_row`.

- [ ] **Step 3: Write the implementation**

```python
def analyze_row(row):
    """Derived fields for one comic. Text fields are None when there is no
    transcript, never 0, so corpus averages cannot be pulled toward zero."""
    transcript = row["transcript"] or ""
    has_transcript = 1 if transcript.strip() else 0

    if has_transcript:
        scene = len(scene_blocks(transcript))
        dialogue = dialogue_lines(transcript)
        speaker_json = json.dumps(speakers(transcript))
    else:
        scene = dialogue = speaker_json = None

    title = row["title"] or ""
    alt = row["alt"] or ""
    return {
        "num": row["num"],
        "scene_blocks": scene,
        "dialogue_lines": dialogue,
        "speakers": speaker_json,
        "has_transcript": has_transcript,
        "is_interactive": 1 if is_interactive(row["num"], row["img_url"]) else 0,
        "title_len": len(title),
        "alt_len": len(alt),
    }


def rebuild_fts(db):
    """Rebuild the search index from the comics table."""
    db.execute("DELETE FROM comics_fts")
    db.execute(
        "INSERT INTO comics_fts (num, title, alt, transcript)"
        " SELECT num, title, alt, transcript FROM comics"
    )
    db.commit()


def run_analyze(db):
    """Recompute every derived field and rebuild the index. Idempotent.
    Returns the number of comics analysed."""
    rows = db.execute(
        "SELECT num, title, alt, transcript, img_url FROM comics ORDER BY num"
    ).fetchall()

    db.executemany(
        """
        UPDATE comics SET
            scene_blocks = :scene_blocks,
            dialogue_lines = :dialogue_lines,
            speakers = :speakers,
            has_transcript = :has_transcript,
            is_interactive = :is_interactive,
            title_len = :title_len,
            alt_len = :alt_len
        WHERE num = :num
        """,
        [analyze_row(row) for row in rows],
    )
    rebuild_fts(db)

    with_transcript = sum(1 for r in rows if (r["transcript"] or "").strip())
    print(
        f"analyzed {len(rows)} comics: {with_transcript} with a transcript, "
        f"{len(rows) - with_transcript} without"
    )
    return len(rows)


def cmd_analyze(args):
    db = connect()
    init_db(db)
    run_analyze(db)
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `46/46 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(analyze): derive text features with honest nulls"
```

---

### Task 7: The `stats` command

**Files:**
- Modify: `xkcd.py` (append after `cmd_analyze`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `connect`, `init_db`, `SYNONYMS`, `expand`, `fts_query`, `run_analyze`
- Produces: `xkcd.corpus_stats(db, top=15) -> dict`, `xkcd.cmd_stats(args) -> int`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on `xkcd.corpus_stats`.

- [ ] **Step 3: Write the implementation**

```python
def _percentiles(values):
    if not values:
        return {"min": None, "median": None, "p90": None, "max": None}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "p90": ordered[int(len(ordered) * 0.9)],
        "max": ordered[-1],
    }


def corpus_stats(db, top=15):
    """Aggregate figures. Transcript-derived metrics carry their own coverage so
    nothing reads as a corpus-wide claim it cannot support."""
    total = db.execute("SELECT COUNT(*) c FROM comics").fetchone()["c"]
    with_transcript = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE has_transcript = 1"
    ).fetchone()["c"]

    scene_values = [
        r[0] for r in db.execute(
            "SELECT scene_blocks FROM comics WHERE scene_blocks IS NOT NULL"
        )
    ]

    speaker_counts = collections.Counter()
    for row in db.execute("SELECT speakers FROM comics WHERE speakers IS NOT NULL"):
        for name in json.loads(row[0]):
            speaker_counts[name] += 1

    topic_counts = {}
    for topic in SYNONYMS:
        query = fts_query(topic)
        if not query:
            continue
        topic_counts[topic] = db.execute(
            "SELECT COUNT(*) c FROM comics_fts WHERE comics_fts MATCH ?", (query,)
        ).fetchone()["c"]

    dates = [
        r[0] for r in db.execute("SELECT date FROM comics WHERE date != ''")
    ]

    return {
        "total": total,
        "with_transcript": with_transcript,
        "without_transcript": total - with_transcript,
        "non_transcript_rows": total - with_transcript,
        "scene_blocks_over": len(scene_values),
        "scene_blocks": _percentiles(scene_values),
        "scene_blocks_median": _percentiles(scene_values)["median"],
        "top_speakers": speaker_counts.most_common(top),
        "topic_counts": topic_counts,
        "date_first": min(dates) if dates else None,
        "date_last": max(dates) if dates else None,
        "title_len": _percentiles(
            [r[0] for r in db.execute("SELECT title_len FROM comics WHERE title_len IS NOT NULL")]
        ),
        "alt_len": _percentiles(
            [r[0] for r in db.execute("SELECT alt_len FROM comics WHERE alt_len IS NOT NULL")]
        ),
    }


def cmd_stats(args):
    db = connect()
    init_db(db)
    s = corpus_stats(db, top=args.top)

    print(f"comics                 {s['total']}")
    print(f"date range             {s['date_first']} .. {s['date_last']}")
    print()
    print("transcript coverage (the rest have title and alt only)")
    print(f"  with a transcript    {s['with_transcript']}")
    print(f"  without              {s['without_transcript']}")
    print()
    print(f"scene blocks (over the {s['scene_blocks_over']} transcripts)")
    for key in ("min", "median", "p90", "max"):
        print(f"  {key:<6}              {s['scene_blocks'][key]}")
    print()
    print("title / alt length")
    for key in ("min", "median", "p90", "max"):
        print(f"  {key:<6}              {s['title_len'][key]:>4} / {s['alt_len'][key]}")
    print()
    print(f"top speakers (of {s['with_transcript']} transcripts)")
    for name, count in s["top_speakers"]:
        print(f"  {count:>5}  {name}")
    print()
    print("topics")
    for topic, count in sorted(s["topic_counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {count:>5}  {topic}")
    return 0
```

Add `import collections` to the imports at the top of `xkcd.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `51/51 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(stats): report corpus aggregates with their coverage"
```

---

### Task 8: The `pack` command

**Files:**
- Modify: `xkcd.py` (append after `cmd_stats`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `connect`, `init_db`, `fts_query`, `expand`, `corpus_stats`, `rebuild_fts`
- Produces: `xkcd.retrieve(db, topic, n=8) -> list[sqlite3.Row]`, `xkcd.format_pack(db, topic, rows) -> str`, `xkcd.cmd_pack(args) -> int`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on `xkcd.retrieve`.

- [ ] **Step 3: Write the implementation**

```python
EXCERPT_CHARS = 900


def retrieve(db, topic, n=8):
    """BM25 hits for a topic, expanded through the synonym map.

    Returns [] when the topic has nothing searchable, which is a valid answer
    rather than an error.
    """
    query = fts_query(topic)
    if not query:
        return []
    numbers = [
        row[0]
        for row in db.execute(
            "SELECT num FROM comics_fts WHERE comics_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, n),
        )
    ]
    if not numbers:
        return []
    marks = ",".join("?" * len(numbers))
    rows = db.execute(
        f"SELECT * FROM comics WHERE num IN ({marks})", numbers
    ).fetchall()
    order = {num: index for index, num in enumerate(numbers)}
    return sorted(rows, key=lambda row: order[row["num"]])


def format_pack(db, topic, rows):
    """One evidence block: exemplars, the speaker roster, and corpus context."""
    stats = corpus_stats(db, top=25)
    lines = [f"# Evidence pack: {topic}", ""]
    lines.append(
        f"Corpus: {stats['total']} comics. {stats['with_transcript']} have a "
        f"transcript (all of #1..#1677); the other {stats['without_transcript']} "
        f"are title and alt text only."
    )
    overlap = stats["topic_counts"].get(topic)
    if overlap is not None:
        lines.append(f"Comics matching this topic by any synonym: {overlap}")
    lines.append("")

    if not rows:
        lines.append(f"No comics matched {topic!r}. Try a broader word.")
        lines.append("")
    else:
        lines.append(f"## Exemplars ({len(rows)})")
        lines.append("")
        for row in rows:
            lines.append(f"### #{row['num']} {row['title']} ({row['date']})")
            lines.append(f"Title: {row['title']}")
            lines.append(f"Alt: {row['alt']}")
            transcript = (row["transcript"] or "").strip()
            if transcript:
                if len(transcript) > EXCERPT_CHARS:
                    transcript = transcript[:EXCERPT_CHARS] + "\n[...truncated]"
                lines.append("Transcript:")
                lines.append(transcript)
            else:
                lines.append("Transcript: none (title and alt only)")
            lines.append("")

    lines.append("## Speakers in the corpus")
    lines.append(", ".join(name for name, _ in stats["top_speakers"]))
    lines.append("")
    return "\n".join(lines)


def cmd_pack(args):
    db = connect()
    init_db(db)
    rows = retrieve(db, args.topic, n=args.n)
    print(format_pack(db, args.topic, rows))
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `58/58 passed`

- [ ] **Step 5: Verify against the real corpus**

Run:

```bash
python3 xkcd.py pack "romance" --n 3
python3 xkcd.py pack 'A - B' --n 2 ; echo "exit=$?"
```

Expected: the first prints three exemplar blocks with `Title:` and `Alt:` lines. The second prints something and exits 0, with no traceback.

- [ ] **Step 6: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(pack): add topic retrieval and evidence pack formatting"
```

---

### Task 9: The `selftest` command

**Files:**
- Modify: `xkcd.py` (append after `cmd_pack`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `connect`, `init_db`
- Produces: `xkcd.run_selftest(db) -> int`, `xkcd.cmd_selftest(args) -> int`

- [ ] **Step 1: Write the failing test**

The selftest asserts against the live corpus, so its unit test only checks that it reports honestly when the corpus is absent or short.

```python
def test_run_selftest_fails_cleanly_on_an_empty_corpus():
    """It must report, not traceback, when the corpus has not been built yet."""
    assert xkcd.run_selftest(tmpdb()) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 test_xkcd.py`
Expected: failure on `xkcd.cmd_selftest`.

- [ ] **Step 3: Write the implementation**

```python
def run_selftest(db):
    """Assert known-good facts against a database. Returns 0 or 1."""
    checks = []

    def check(label, got, want):
        checks.append((label, got == want, got, want))

    total = db.execute("SELECT COUNT(*) c FROM comics").fetchone()["c"]
    if total < 100:
        print(f"corpus has only {total} comics; run `xkcd.py fetch` first")
        return 1

    row = db.execute("SELECT * FROM comics WHERE num = 1").fetchone()
    check("#1 alt", row["alt"], "Don't we all.")
    check("#1 scene blocks", row["scene_blocks"], 2)
    check("#1 speakers", json.loads(row["speakers"]), ["Boy"])
    check("#1 image path is 0001.jpg", (row["img_path"] or "").endswith("0001.jpg"), True)

    row = db.execute("SELECT * FROM comics WHERE num = 300").fetchone()
    check("#300 scene blocks (inline stage direction)", row["scene_blocks"], 0)
    check("#300 speakers", json.loads(row["speakers"]), ["Boy", "Girl"])

    check("#404 absent",
          db.execute("SELECT COUNT(*) c FROM comics WHERE num = 404").fetchone()["c"], 0)

    with_transcript = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE has_transcript = 1").fetchone()["c"]
    check("comics with a transcript", with_transcript, 1665)
    check("comics without a transcript", total - with_transcript, 1636)
    check("total comics", total, 3301)

    check("all transcripts are #1..#1677",
          db.execute("SELECT MAX(num) m FROM comics WHERE has_transcript = 1").fetchone()["m"],
          1677)

    nulls = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE has_transcript = 0 AND"
        " (scene_blocks IS NOT NULL OR dialogue_lines IS NOT NULL OR speakers IS NOT NULL)"
    ).fetchone()["c"]
    check("no transcript-less row carries derived text", nulls, 0)

    leaking = db.execute(
        "SELECT num FROM comics WHERE speakers LIKE '%Title text%'"
    ).fetchall()
    check("no metadata label leaked into speakers", [r[0] for r in leaking], [])

    zombies = db.execute(
        "SELECT num FROM comics WHERE has_transcript = 1 AND scene_blocks IS NULL"
    ).fetchall()
    check("every transcript has a scene-block value", [r[0] for r in zombies], [])

    bad_images = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE img_path IS NOT NULL AND (img_bytes IS NULL OR img_bytes = 0)"
    ).fetchone()["c"]
    check("no zero-byte images recorded", bad_images, 0)

    failed = 0
    for label, ok, got, want in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            failed += 1
            print(f"       got  {got!r}")
            print(f"       want {want!r}")

    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


def cmd_selftest(args):
    db = connect()
    init_db(db)
    return run_selftest(db)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 test_xkcd.py`
Expected: `59/59 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(selftest): assert corpus invariants against the live database"
```

---

### Task 10: Fetch and analyse the full corpus

**Files:**
- Modify: `data/` (gitignored build output)
- Modify: `README.md` (create: how to rebuild the corpus)

**Interfaces:**
- Consumes: every command above
- Produces: `data/xkcd.db`, `data/comics/*`

- [ ] **Step 1: Create the README**

```markdown
# xkcd corpus

A local archive of every xkcd comic, plus a skill that writes new ones.

## Rebuild the corpus

```bash
python3 xkcd.py fetch      # ~3300 metadata + image requests, 20 to 40 minutes
python3 xkcd.py analyze    # derive text features, seconds
python3 xkcd.py selftest   # assert the invariants, seconds
python3 xkcd.py stats      # print corpus aggregates
python3 xkcd.py pack "gardening"   # retrieve exemplars for a topic
```

`data/` is gitignored. It is reproducible output, roughly 300 to 600MB.

## Tests

```bash
python3 test_xkcd.py
```

No network, no test framework.

## Writing a comic

Ask pi to write an xkcd comic about a topic. The `xkcd-write` skill reads
`.agents/skills/xkcd-write/references/style-guide.md` and runs `pack` for
evidence.

## Corpus shape

Of 3301 comics, 1665 have a transcript. Transcripts stop at `#1677`. The rest
have a title and alt text only, so every transcript-derived statistic is scoped
to the first half.
```

- [ ] **Step 2: Run the full fetch**

Run: `python3 xkcd.py fetch`

Expected, at the end: `fetched 3301, skipped 0, failed 0`, and exit code 0. Two comics (`#1608`, `#1663`) record no image because they have no static one; that is not a failure. If any real failures are listed, re-run the same command: it resumes and retries only the failed images. Repeat until failures are 0.

- [ ] **Step 3: Analyse**

Run: `python3 xkcd.py analyze`

Expected: `analyzed 3301 comics: 1665 with a transcript, 1636 without`

- [ ] **Step 4: Assert the invariants**

Run: `python3 xkcd.py selftest; echo "exit=$?"`

Expected: `15/15 checks passed`, `exit=0`. If a check fails, the corpus or the parser is wrong. Investigate before continuing; do not adjust the expected value to match the output unless the spec also changes.

- [ ] **Step 5: Verify rows equal images on disk**

Run:

```bash
python3 - <<'PY'
import sqlite3, pathlib
db = sqlite3.connect("data/xkcd.db")
rows = db.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
with_img = db.execute("SELECT COUNT(*) FROM comics WHERE img_path IS NOT NULL").fetchone()[0]
no_img = db.execute("SELECT COUNT(*) FROM comics WHERE img_path IS NULL").fetchone()[0]
files = list(pathlib.Path("data/comics").glob("*"))
zero = [f for f in files if f.stat().st_size == 0]
parts = list(pathlib.Path("data/comics").glob("*.part"))
print(f"rows={rows} rows_with_image={with_img} rows_without={no_img}")
print(f"files_on_disk={len(files)} zero_byte={len(zero)} leftover_part_files={len(parts)}")
assert rows == 3301, rows
assert with_img + no_img == rows
assert len(files) == with_img, (len(files), with_img)
assert not zero, zero
assert not parts, parts
print("OK")
PY
```

Expected: `rows=3301`, `files_on_disk` equal to `rows_with_image`, `zero_byte=0`, `leftover_part_files=0`, then `OK`.

- [ ] **Step 6: Capture the real statistics**

Run: `python3 xkcd.py stats --top 25 > docs/corpus-stats.txt && cat docs/corpus-stats.txt`

Expected: real numbers matching the constraint table. If any figure disagrees with the table, stop and report it rather than editing the table.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/corpus-stats.txt
git commit -m "docs: add corpus README and measured statistics"
```

The database and images are not committed. They are reproducible from `fetch`.

---

### Task 11: Write the style guide

**Files:**
- Create: `.agents/skills/xkcd-write/references/style-guide.md`
- Read: `docs/corpus-stats.txt`, `data/xkcd.db`

**Interfaces:**
- Consumes: `stats`, `pack`, and the live database
- Produces: a style guide the skill reads. No code.

- [ ] **Step 1: Gather the evidence**

Run each of these and read the output before writing a word:

```bash
python3 xkcd.py stats --top 30
python3 xkcd.py pack "existential" --n 6
python3 xkcd.py pack "programming" --n 6
python3 xkcd.py pack "romance" --n 6
python3 xkcd.py pack "cats" --n 4
python3 xkcd.py pack "meta" --n 4
```

For alt-text form specifically, sample the 20 longest and 20 shortest:

```bash
python3 - <<'PY'
import sqlite3
db = sqlite3.connect("data/xkcd.db")
db.row_factory = sqlite3.Row
short = db.execute("SELECT num, title, alt FROM comics ORDER BY alt_len LIMIT 20").fetchall()
long_ = db.execute("SELECT num, title, alt FROM comics ORDER BY alt_len DESC LIMIT 20").fetchall()
for label, rows in (("SHORTEST", short), ("LONGEST", long_)):
    print(f"--- {label} alt texts")
    for r in rows:
        print(f"#{r['num']} {r['title']}: {r['alt']}")
PY
```

- [ ] **Step 2: Write the guide**

Every claim in the guide cites a number from Step 1. No unsourced assertions about what xkcd "usually" does.

The guide must cover:

1. **Length.** Real title and alt length distributions. The measured median alt is 115 characters; state the range the writer should target.
2. **What the alt text does.** Study the samples and describe the actual function. It is a second joke or a sideways observation, not a summary of the comic.
3. **Structure.** Scene-block distribution, and the fact that the median transcript contains a single scene-setting block followed by dialogue. Panel counts from the standing-block data.
4. **Speakers.** The measured roster (`Man`, `Woman`, `Person 1`, `Narrator`, `Figure` and so on). State plainly that xkcd does not name characters in transcripts, so the writer should use role labels.
5. **Topics.** The measured counts per topic. Name the ones with real depth and the ones with almost none.
6. **Recurring devices.** Derived from the exemplar packs, with comic numbers cited.
7. **Anti-patterns.** What the corpus never does: no narration explaining the joke, no character names, no alt text that restates the title.
8. **Coverage warning.** Half the corpus has no transcript, so any structural claim is grounded in `#1..#1677`.

- [ ] **Step 3: Verify every number in the guide**

Run:

```bash
grep -nE "[0-9]{2,}" .agents/skills/xkcd-write/references/style-guide.md
```

Check each number against `docs/corpus-stats.txt` or the pack output. Fix any that do not match. This step exists because a style guide with invented statistics is worse than no style guide.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/xkcd-write/references/style-guide.md
git commit -m "docs(skill): add xkcd style guide derived from corpus measurements"
```

---

### Task 12: The `xkcd-write` skill and end-to-end check

**Files:**
- Create: `.agents/skills/xkcd-write/SKILL.md`

**Interfaces:**
- Consumes: `python3 xkcd.py pack "<topic>"`, `references/style-guide.md`
- Produces: a comic script in the fixed format

- [ ] **Step 1: Write the skill**

The frontmatter `description` must carry the trigger words, because that is what pi matches against.

```markdown
---
name: xkcd-write
description: Write a new xkcd-style comic script on any topic. Use when asked to "write an xkcd comic about X", "make a comic in the style of xkcd", "xkcd about Y", "write an xkcd script", or to produce a stick-figure comic script with a title and alt text. Produces title, alt text, and a panel script, not an image.
---

# Writing an xkcd comic

## What you produce

Exactly this format, and nothing else:

```
Title: <title>
Alt: <alt text>

[[scene description for panel 1]]
Man: <line>
[[scene description for panel 2]]
Woman: <line>
```

- `Title:` one line. Follow the corpus title-length distribution in the style guide.
- `Alt:` one line. This is a **second joke**, never a summary of the comic. It is
  the single most characteristic piece of xkcd writing, and the easiest to get
  wrong.
- A blank line, then the panel script.
- `[[...]]` holds a scene description. It must stand alone on its line.
- `Speaker: line` holds dialogue. A line may continue over several physical lines.

## How to do it

1. Read `references/style-guide.md` in full.
2. Run the retrieval command for the topic, and read the evidence:

```bash
python3 xkcd.py pack "<topic>" --n 8
```

3. Read the exemplars. Notice what they do, not just what they say.
4. Draft. Then check the draft against every rule below before showing it.

If the pack reports no matches, say so, and write from the style guide alone.
Still produce the comic.

## Hard rules

- **Alt text is a second joke.** If the alt text would work as a summary of the
  panels, it is wrong. Rewrite it.
- **No named characters.** The corpus uses role labels: `Man`, `Woman`,
  `Person 1`, `Narrator`, `Figure`, `Girl`. Never invent a name like "Cueball"
  or "Alice". Measured: `Cueball` appears in no transcript.
- **One to four panels.** The corpus median scene-block count is 1 and the p90 is
  5. Long scripts are not xkcd.
- **Never explain the punchline.** State the premise, land the joke, stop. No
  narrator line that tells the reader what to think.
- **The scene description is spare.** `[[A boy sits in a barrel which is floating
  in an ocean.]]` is the register. Not a paragraph of staging.
- **Do not describe visual style in the script.** Stick figures are a given.
- **No em dashes. No exclamation-heavy dialogue.** Read the exemplars for voice.

## Self-check before showing the draft

Confirm each of these, and say which ones you checked:

- The alt text is a joke, not a summary.
- No speaker is a proper name.
- The panel count is between 1 and 4.
- Every `[[...]]` stands alone on its own line.
- The joke is not explained after the punchline.
- The topic actually appears, rather than being mentioned once and abandoned.
```

- [ ] **Step 2: Verify the skill loads**

Run: `/reload`
Expected: no warning about `xkcd-write`. A malformed `SKILL.md` or a missing `description` produces a load warning.

- [ ] **Step 3: Write three comics on topics absent from the corpus**

Choose topics with no xkcd comics at all. Good candidates: `sourdough starter maintenance`, `noise-cancelling headphones`, `swimming lane etiquette`. Confirm each is genuinely absent first:

```bash
python3 xkcd.py pack "sourdough starter maintenance" --n 3
python3 xkcd.py pack "noise-cancelling headphones" --n 3
python3 xkcd.py pack "swimming lane etiquette" --n 3
```

Expected: each reports `No comics matched` or returns only weak matches. If a topic has strong matches, pick a different topic. The point is writing about something xkcd never covered.

Then write all three using the skill.

- [ ] **Step 4: Check the output against the rules**

For each of the three scripts, verify by inspection:

| Check | How |
| --- | --- |
| Format is exact | Three sections: `Title:`, `Alt:`, blank line, panel script |
| Alt is a joke | Read it. If it summarises the panels, it fails |
| No proper names as speakers | Every speaker is a role label |
| 1 to 4 panels | Count `[[...]]` blocks |
| Scene blocks stand alone | Each `[[...]]` on its own line |
| Punchline not explained | The script stops after the joke |

Report any script that fails and rewrite it. Do not report a script as done without having run this check.

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/xkcd-write/SKILL.md
git commit -m "feat(skill): add the xkcd-write comic script skill"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task. Raw store and schema to Task 1. `fetch` to Tasks 4 and 5. `analyze` and the null rule to Task 6. `stats` to Task 7. Retrieval and the synonym map to Tasks 3 and 8. `selftest` to Task 9. Writer output format and the skill to Task 12. Style guide to Task 11. Testing and verification to Tasks 1 through 10. The one spec item with no task is `extra_parts`, which needs no code: `upsert_comic` reads named keys only, and Task 5's `test_upsert_comic_ignores_unknown_keys` pins that.

**Placeholders.** None. Every step carries real code, real commands, and real expected output.

**Type consistency.** Verified across tasks: `connect`, `init_db`, `build_parser`, `main`, `strip_metadata`, `scene_blocks`, `speakers`, `dialogue_lines`, `expand`, `fts_query`, `_get`, `request_json`, `image_filename`, `encode_image_url`, `has_static_image`, `is_interactive`, `download_image`, `upsert_comic`, `image_dest`, `needs_image`, `analyze_row`, `rebuild_fts`, `run_analyze`, `corpus_stats`, `retrieve`, `format_pack`, `run_selftest`. Every command whose logic needs a unit test is split into a `run_*` or pure function that takes a database, with `cmd_*` left as a thin wrapper that connects and calls it. That is why no test needs an argparse stand-in.

**Test counts.** Per task: 7, 9, 8, 8, 8, 6, 5, 7, 1. Running totals: 7, 16, 24, 32, 40, 46, 51, 58, 59. If a count does not match when you run it, the plan and the code have diverged; fix whichever is wrong before committing.

**Review Focus coverage.** Item 1 (no transcript) is pinned by `test_analyze_row_nulls_every_text_field_without_a_transcript` in Task 6 and re-checked in Task 9's selftest. Item 2 (metacharacters) is pinned by `test_fts_query_never_raises_on_metacharacters` in Task 3 and `test_retrieve_never_raises_on_hostile_topics` in Task 8. Item 3 (no image, animated) by `test_is_interactive_covers_all_three_detection_mechanisms` in Task 4. Item 4 (awkward filenames) by `test_encode_image_url_percent_encodes_awkward_filenames` in Task 4 and the live check in Task 5 Step 5. Item 5 (interrupted fetch) by `test_needs_image_true_when_a_previous_download_failed` in Task 5 and the resume check in Task 5 Step 5.

**One known gap, stated rather than hidden.** `selftest` hardcodes 1665, 1636, 3301, and 1677. Those come from the measurement table and will need updating when xkcd publishes more comics. That is intentional: a change in the corpus should be noticed, not silently absorbed.

The earlier draft of this plan had two more gaps, both now closed. The analyze test wrote to the real `data/xkcd.db`; extracting `run_analyze(db)` made it hermetic. The plan also asserted test counts that did not match its own test functions; the counts above are now derived by counting them.
