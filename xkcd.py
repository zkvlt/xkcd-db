#!/usr/bin/env python3
"""xkcd corpus tool. Fetches every comic, analyses the text, and serves evidence
for the xkcd-write skill.

Subcommands: fetch, analyze, stats, pack, selftest.
"""

from __future__ import annotations

import argparse
import collections
import html
import io
import json
import re
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

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
    alt_len         INTEGER,
    explain_transcript  TEXT,
    explain_fetched_at  TEXT,
    explain_incomplete  INTEGER,
    transcript_source   TEXT
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


# Columns added after the table was first created. CREATE TABLE IF NOT EXISTS
# will not add them to an existing database, and there is a live 3301-row corpus
# that must upgrade in place rather than be re-fetched for 61 minutes.
MIGRATIONS = {
    "explain_transcript": "TEXT",
    "explain_fetched_at": "TEXT",
    "explain_incomplete": "INTEGER",
    "transcript_source": "TEXT",
}


def migrate(db):
    """Add any columns the existing table is missing. Idempotent.

    The column names come from MIGRATIONS, whose keys are literal identifiers in
    this file, so no outside value reaches the SQL.
    """
    have = {row[1] for row in db.execute("PRAGMA table_info(comics)")}
    for column, kind in MIGRATIONS.items():
        if column not in have:
            db.execute(f"ALTER TABLE comics ADD COLUMN {column} {kind}")
    db.commit()


def init_db(db):
    """Create the schema if absent, then add any columns added since."""
    db.executescript(SCHEMA)
    migrate(db)
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

# The literal metadata labels measured in the corpus. A bare `Title text:` line
# outside braces is what these look like, so none may ever become a speaker.
# Distinct from META_LABELS, which is a prefix filter used to reject them at
# parse time: `Map Title Text` starts with `Map` and is a panel label drawn on a
# map, which is content, so a substring test would wrongly reject it.
META_LABEL_NAMES = frozenset({
    "title", "title text", "title-text", "panel title", "alt", "alt text",
    "alt-text", "subtitle", "subheading", "headline", "legend", "citation",
    "footnote", "mouseover", "mouseover text", "rollover text",
    "author's comment", "options",
})


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


EXPLAIN_URL = "https://www.explainxkcd.com/wiki/index.php/{num}"
EXPLAIN_USER_AGENT = (
    "xkcd-corpus/1.0 (personal archive; 1 request/second; contact: local user)"
)

# Where a Transcript section ends. The raw page inlines the whole Talk section
# after the transcript, so the boundary matters: terminating only on <h2> once
# returned 16507 characters for #1700 where the real transcript is 951.
TRANSCRIPT_END_MARKERS = (
    '<div style="clear: both">',
    '<span id="discussion">',
    "<h1",
    '<div id="catlinks"',
    '<div class="printfooter"',
)

# Present in the Talk section and the category footer, never in a transcript.
LEAK_MARKERS = (
    "Add comment",
    "Create topic",
    "Retrieved from",
    "Category:",
    "Privacy policy",
)

NOTICE_RE = re.compile(
    r"^This is one of [\d,]+ incomplete transcripts?:.*?editing the transcript!?\s*",
    re.S | re.I,
)
BLOCK_CLOSE_RE = re.compile(r"</(?:p|div|li|ul|ol|dd|dt|dl)>", re.I)
BR_RE = re.compile(r"<br\s*/?>", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _get_html(url, timeout):
    """Seam for explainxkcd HTML, kept separate from _get so the existing
    request tests and their 2-argument monkeypatches are untouched."""
    return requests.get(
        url, timeout=timeout, headers={"User-Agent": EXPLAIN_USER_AGENT}
    ).text


def fetch_explain_html(num):
    """The raw wiki page for one comic."""
    return _get_html(EXPLAIN_URL.format(num=num), 30)


def has_leaked_markup(text):
    """True when Talk-page or footer content ended up in a transcript."""
    low = (text or "").lower()
    return any(marker.lower() in low for marker in LEAK_MARKERS)


def extract_transcript(page):
    """(text, incomplete) for an explainxkcd page.

    Returns ("", False) when the page has no Transcript section, which is a
    valid outcome rather than an error.
    """
    page = page or ""
    heading = re.search(r'<h2[^>]*>.*?id="Transcript".*?</h2>', page, re.S)
    if not heading:
        return "", False

    start = heading.end()
    stops = [page.find(marker, start) for marker in TRANSCRIPT_END_MARKERS]
    stops = [stop for stop in stops if stop != -1]
    end = min(stops) if stops else len(page)

    body = page[start:end]
    text = BR_RE.sub("\n", BLOCK_CLOSE_RE.sub("\n", body))
    text = html.unescape(TAG_RE.sub("", text))
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()

    incomplete = bool(NOTICE_RE.match(text))
    text = NOTICE_RE.sub("", text).strip()
    return text, incomplete


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


def comic_numbers(latest_num, limit=None):
    """Comic numbers 1..latest, excluding the nonexistent #404.

    `limit` counts comics, and `limit=0` means none. A truthiness check on the
    limit would turn `--limit 0` into a full corpus fetch, which is exactly what
    it did before this function existed.
    """
    numbers = [n for n in range(1, latest_num + 1) if n != 404]
    if limit is not None:
        numbers = numbers[:limit]
    return numbers


def cmd_fetch(args):
    db = connect()
    init_db(db)

    latest = request_json(LATEST_URL)
    if latest is None:
        print("error: could not read the latest comic number", file=sys.stderr)
        return 2

    numbers = comic_numbers(latest["num"], args.limit)

    fetched = skipped = 0
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

    dates = [r[0] for r in db.execute("SELECT date FROM comics WHERE date != ''")]

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
    print(format_stats(corpus_stats(db, top=args.top)))
    return 0


def _fmt(value):
    """A percentile renders as '-' when there is no data to compute it from."""
    return "-" if value is None else value


def format_stats(s):
    """Render corpus statistics as text. Safe on an empty corpus, where every
    percentile is None."""
    lines = [
        f"comics                 {s['total']}",
        f"date range             {s['date_first'] or '-'} .. {s['date_last'] or '-'}",
        "",
        "transcript coverage (the rest have title and alt only)",
        f"  with a transcript    {s['with_transcript']}",
        f"  without              {s['without_transcript']}",
        "",
        f"scene blocks (over the {s['scene_blocks_over']} transcripts)",
    ]
    for key in ("min", "median", "p90", "max"):
        lines.append(f"  {key:<6}              {_fmt(s['scene_blocks'][key])}")
    lines += ["", "title / alt length"]
    for key in ("min", "median", "p90", "max"):
        lines.append(
            f"  {key:<6}              {_fmt(s['title_len'][key]):>4} / {_fmt(s['alt_len'][key])}"
        )
    lines += ["", f"top speakers (of {s['with_transcript']} transcripts)"]
    for name, count in s["top_speakers"]:
        lines.append(f"  {count:>5}  {name}")
    lines += ["", "topics"]
    for topic, count in sorted(s["topic_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {count:>5}  {topic}")
    return "\n".join(lines)


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

    leaked = []
    for row in db.execute("SELECT num, speakers FROM comics WHERE speakers IS NOT NULL"):
        for name in json.loads(row["speakers"]):
            if name.strip().lower() in META_LABEL_NAMES:
                leaked.append((row["num"], name))
    check("no metadata label leaked into speakers", leaked, [])

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
