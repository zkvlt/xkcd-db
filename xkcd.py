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
    """How many Speaker: lines the transcript contains, excluding metadata labels.

    Applies the same label rejection as `speakers` so the two fields agree; a
    bare `Title text:` line would otherwise count as dialogue in about ten
    comics.
    """
    count = 0
    for match in SPEAKER_RE.finditer(strip_metadata(transcript)):
        if not META_LABELS.match(match.group(1).strip()):
            count += 1
    return count


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
