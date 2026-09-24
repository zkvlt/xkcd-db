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
