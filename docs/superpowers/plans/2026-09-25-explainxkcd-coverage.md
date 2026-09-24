# explainxkcd Transcript Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every comic in the corpus structured transcript data by adding explainxkcd's transcripts as a second, separately-stored source.

**Architecture:** One new command, `fetch-explain`, writes three nullable columns onto `comics`. `analyze` then derives `scene_blocks`, `dialogue_lines`, `speakers`, and `transcript_source` from a coalesced transcript, official text preferred. The sources are never merged in storage or pooled in statistics.

**Tech Stack:** Python 3.12, stdlib `re`/`html`/`sqlite3`, `requests` for HTTP. No new dependencies. Tests stay framework-free via `python3 test_xkcd.py`.

**Spec:** `docs/superpowers/specs/2026-09-25-explainxkcd-coverage-design.md`

## Global Constraints

- **No MediaWiki API.** `robots.txt` disallows `/wiki/api.php`. Article HTML only, from `https://www.explainxkcd.com/wiki/index.php/<num>`.
- **One request per second, single-threaded.** `Crawl-delay: 1` in robots.txt. No thread pools, no parallelism.
- **A User-Agent naming the tool and the rate.** `xkcd-corpus/1.0 (personal archive; 1 request/second; contact: local user)`.
- **Do not modify `fetch` or its tests.** The new work is additive. `_get` keeps its current 2-argument signature.
- Three-party imports stay at `requests` and `PIL`. Standard library otherwise.
- Exit codes: `0` clean, `1` completed with failures, `2` hard error.
- Derived text fields are `NULL`, never `0`, when no transcript exists from either source.
- Speaker counts are **split by source, never pooled**. `Man` (official) and `Megan` (explainxkcd) are different conventions.
- `data/` is gitignored and stays that way. explainxkcd text is CC BY-SA 3.0 and carries attribution and share-alike obligations if the corpus is ever published.

## Measured Facts These Tasks Assume

From reconnaissance on 2026-09-25. Do not re-derive; assert against them.

| Fact | Value |
| --- | --- |
| Comics without an official transcript | 1636, first is `#1609`, last is `#3302` |
| explainxkcd coverage | Every comic probed from `#1609` to `#3302` has a Transcript section, including the latest |
| Scene block syntax | explainxkcd uses line-standing `[scene]`; xkcd uses `[[scene]]` |
| Character naming | explainxkcd names characters; xkcd uses role labels |
| Boundary that ends the section | `<div style="clear: both">` in all 12 probes |
| Extractor accuracy after the fix | 12 of 12 probes clean, 0 leaked markers |
| Incomplete-transcript notice | Claims 36 in total across the wiki |
| Expected crawl cost | ~28 minutes at 1 req/sec |

## Review Focus

Five input classes the spec implies but no single task's happy-path tests cover. Each has a test in the task that owns the code.

1. **An existing 3301-row database gaining new columns.** `CREATE TABLE IF NOT EXISTS` does not add columns to a table that already exists, so without a migration every existing row is missing the new fields. A reasonable person expects their already-built corpus to upgrade in place rather than needing a 61-minute re-fetch. Owned by Task 1.
2. **The Talk section leaking into a stored transcript.** This is the exact failure that broke the first extractor: `#1700` returned 16,507 characters where the real transcript is 951, and 5 of 10 probes were contaminated. A reasonable person expects a stored transcript to be the transcript. Owned by Task 2 and re-checked at scale in Task 8.
3. **A page with no Transcript section, or a wiki error page.** A reasonable person expects it recorded as fetched-and-empty and reported, not stored as a transcript and not retried forever. Owned by Task 3.
4. **Re-running the fetch after a partial run.** A reasonable person expects fetched rows skipped, failed rows retried, and nothing duplicated or refetched. Owned by Task 3 and verified live in Task 8.
5. **`--limit 0` on the new command.** The same falsy-zero bug already fixed once in `fetch`, where `--limit 0` started a full corpus download. Owned by Task 3.

---

## File Structure

| File | Change |
| --- | --- |
| `xkcd.py` | Add migration, extraction, `fetch-explain`, coalescing, and updates to analyze/stats/pack/selftest |
| `test_xkcd.py` | Add tests; update two fixtures and the speaker assertions that change shape |
| `README.md` | Attribution section and the new command |
| `.agents/skills/xkcd-write/references/style-guide.md` | Coverage and naming rules |
| `docs/corpus-stats.txt` | Regenerated |

No new files. `xkcd.py` is already 841 lines; if it passes roughly 950 consider splitting, since the earlier review flagged the ~800 mark and it was deferred.

---

### Task 1: Schema migration

**Files:**
- Modify: `xkcd.py` (SCHEMA block, `init_db`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: nothing
- Produces: `xkcd.MIGRATIONS`, `xkcd.migrate(db) -> None`; `init_db` now calls it

- [ ] **Step 1: Write the failing tests**

```python
def columns(db, table="comics"):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def test_init_db_creates_the_new_explainxkcd_columns():
    cols = columns(tmpdb())
    for name in ("explain_transcript", "explain_fetched_at", "explain_incomplete",
                 "transcript_source"):
        assert name in cols, name


def test_migrate_adds_columns_to_an_existing_table():
    """Review Focus 1: CREATE TABLE IF NOT EXISTS does not add columns."""
    db = tmpdb()
    db.execute("ALTER TABLE comics DROP COLUMN explain_transcript")
    db.commit()
    assert "explain_transcript" not in columns(db)

    xkcd.migrate(db)

    assert "explain_transcript" in columns(db)


def test_migrate_preserves_existing_rows():
    """An already-built corpus upgrades in place; nothing is re-fetched."""
    db = tmpdb()
    xkcd.upsert_comic(db, PAYLOAD_1)
    xkcd.migrate(db)
    assert db.execute("SELECT COUNT(*) c FROM comics").fetchone()["c"] == 1
    assert db.execute("SELECT title FROM comics").fetchone()["title"] == "Barrel - Part 1"


def test_migrate_is_idempotent():
    db = tmpdb()
    xkcd.migrate(db)
    xkcd.migrate(db)
    assert "explain_transcript" in columns(db)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on `test_init_db_creates_the_new_explainxkcd_columns` and `AttributeError: module 'xkcd' has no attribute 'migrate'`.

- [ ] **Step 3: Write the implementation**

Append the four columns to the `comics` table in `SCHEMA`, after `alt_len`:

```sql
    explain_transcript  TEXT,
    explain_fetched_at  TEXT,
    explain_incomplete  INTEGER,
    transcript_source   TEXT
```

Then add, immediately after `init_db`:

```python
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
    """Add any columns the existing table is missing. Idempotent."""
    have = {row[1] for row in db.execute("PRAGMA table_info(comics)")}
    for column, kind in MIGRATIONS.items():
        if column not in have:
            db.execute(f"ALTER TABLE comics ADD COLUMN {column} {kind}")
    db.commit()
```

Change `init_db` to run it:

```python
def init_db(db):
    """Create the schema if absent, then add any columns added since."""
    db.executescript(SCHEMA)
    migrate(db)
    db.commit()
```

The `ALTER TABLE` statement is built from the module-level `MIGRATIONS` dict, whose keys are literal identifiers, so no value from outside this file reaches the SQL.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `67/67 passed`

- [ ] **Step 5: Verify against the live corpus**

Run:

```bash
python3 - <<'PY' 2>/dev/null
import xkcd
db = xkcd.connect(); xkcd.init_db(db)
cols = {r[1] for r in db.execute("PRAGMA table_info(comics)")}
print("new columns:", sorted(cols & set(xkcd.MIGRATIONS)))
print("rows preserved:", db.execute("SELECT COUNT(*) FROM comics").fetchone()[0])
PY
```

Expected: all four columns present and `rows preserved: 3301`. This is the point of the task: the real corpus upgrades without a re-fetch.

- [ ] **Step 6: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(db): migrate the corpus in place for explainxkcd columns"
```

---

### Task 2: Page fetch and transcript extraction

**Files:**
- Modify: `xkcd.py` (append after `download_image`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: nothing
- Produces: `xkcd.EXPLAIN_URL`, `xkcd.EXPLAIN_USER_AGENT`, `xkcd.TRANSCRIPT_END_MARKERS`, `xkcd.LEAK_MARKERS`, `xkcd._get_html(url, timeout)`, `xkcd.fetch_explain_html(num) -> str`, `xkcd.extract_transcript(page) -> tuple[str, bool]`, `xkcd.has_leaked_markup(text) -> bool`

- [ ] **Step 1: Write the failing tests**

Fixtures mirror the markup observed live, including the boundary that broke the first attempt. They are small and synthetic rather than copied wiki text, which also keeps CC BY-SA content out of the repository.

```python
# Mirrors the real page structure: the Transcript section, then the Talk section
# inlined after a clear-float div. The leak markers are the ones present on the
# live pages, including mention of the real Talk: URL shape.
EXPLAIN_PAGE = """<html><body>
<h2><span class="mw-headline" id="Transcript">Transcript</span>\
<span class="mw-editsection">[edit]</span></h2>
<dl><dd>[Megan is standing in front of a chart.]</dd>\
<dd>Megan: Only two instruments remain.</dd></dl>
<p><br></p><div style="clear: both"></div><p><span id="discussion"></span>\
<b>Add comment</b> &nbsp; Create topic (use sparingly)</p>
<h1><span class="mw-headline" id="Discussion">Discussion</span></h1>
<p>I think the chart is wrong.</p>
<div>Retrieved from "https://www.explainxkcd.com/wiki/index.php/3302"</div>
<div id="catlinks"><p class="catlinks">Category: Comics</p></div>
</body></html>"""

EXPLAIN_PAGE_INCOMPLETE = """<html><body>
<h2><span class="mw-headline" id="Transcript">Transcript</span></h2>
This is one of 36 incomplete transcripts:
Don't remove this notice too soon. You can help by editing the transcript!
<dl><dd>[Megan is standing in front of a chart.]</dd>\
<dd>Megan: Only two instruments remain.</dd></dl>
<p><br></p><div style="clear: both"></div>
<h1><span class="mw-headline" id="Discussion">Discussion</span></h1>
<p>Retrieved from "https://www.explainxkcd.com/wiki/index.php/3302"</p>
</body></html>"""

EXPLAIN_PAGE_NO_SECTION = """<html><body>
<h2><span class="mw-headline" id="Explanation">Explanation</span></h2>
<p>Some prose about the comic.</p>
</body></html>"""


def test_extract_transcript_returns_the_section_text():
    text, incomplete = xkcd.extract_transcript(EXPLAIN_PAGE)
    assert "[Megan is standing in front of a chart.]" in text
    assert "Megan: Only two instruments remain." in text
    assert incomplete is False


def test_extract_transcript_does_not_leak_the_talk_section():
    """Review Focus 2: the exact bug that returned 16507 chars for #1700."""
    text, _ = xkcd.extract_transcript(EXPLAIN_PAGE)
    assert xkcd.has_leaked_markup(text) is False
    for marker in ("Add comment", "Create topic", "Retrieved from", "Category:"):
        assert marker not in text, marker


def test_extract_transcript_strips_the_incomplete_notice_and_flags_it():
    text, incomplete = xkcd.extract_transcript(EXPLAIN_PAGE_INCOMPLETE)
    assert incomplete is True
    assert "incomplete transcript" not in text.lower()
    assert "Don't remove this notice" not in text
    assert "[Megan is standing in front of a chart.]" in text


def test_extract_transcript_returns_empty_when_there_is_no_section():
    """Review Focus 3, at the parsing level."""
    assert xkcd.extract_transcript(EXPLAIN_PAGE_NO_SECTION) == ("", False)
    assert xkcd.extract_transcript("") == ("", False)


def test_extract_transcript_unescapes_entities_and_drops_tags():
    page = ('<h2><span class="mw-headline" id="Transcript">Transcript</span></h2>'
            '<dl><dd>[A &amp; B &lt;tag&gt;]</dd></dl>'
            '<div style="clear: both"></div>')
    text, _ = xkcd.extract_transcript(page)
    assert text == "[A & B <tag>]"


def test_has_leaked_markup_detects_each_marker():
    for marker in xkcd.LEAK_MARKERS:
        assert xkcd.has_leaked_markup(f"line one\n{marker}\nline two") is True
    assert xkcd.has_leaked_markup("[clean scene]\nMan: hello") is False


def test_fetch_explain_html_uses_the_seam():
    calls = {}

    def fake(url, timeout):
        calls["url"] = url
        return EXPLAIN_PAGE

    original = xkcd._get_html
    xkcd._get_html = fake
    try:
        page = xkcd.fetch_explain_html(3302)
    finally:
        xkcd._get_html = original
    assert calls["url"] == "https://www.explainxkcd.com/wiki/index.php/3302"
    assert "Transcript" in page
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: `AttributeError: module 'xkcd' has no attribute 'extract_transcript'`.

- [ ] **Step 3: Write the implementation**

Add `import html` to the stdlib imports. Then append after `download_image`:

```python
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

# Present in the Talk section and category footer, never in a transcript.
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
    requests tests and their 2-argument monkeypatches are untouched."""
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
```

Note that `html` is imported as a module and the parameter above is named `page`, so there is no shadowing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `74/74 passed`

- [ ] **Step 5: Verify against real pages, including the one that broke it**

Run:

```bash
python3 - <<'PY' 2>/dev/null
import xkcd, time
for num in (1700, 3300, 3302):
    text, incomplete = xkcd.extract_transcript(xkcd.fetch_explain_html(num))
    print(f"#{num}: {len(text):5} chars | incomplete={incomplete} | leaked={xkcd.has_leaked_markup(text)}")
    print("      ", text.splitlines()[-1][:80] if text else "(empty)")
    time.sleep(1.0)
PY
```

Expected: `#1700` around 951 characters (not 16,507), all three with `leaked=False`, and `#3302` around 1,064 characters. This is Review Focus 2 confirmed against the real page that exposed it.

- [ ] **Step 6: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(explain): fetch and extract explainxkcd transcripts"
```

---

### Task 3: The `fetch-explain` command

**Files:**
- Modify: `xkcd.py` (parser, append after `cmd_fetch`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `connect`, `init_db`, `fetch_explain_html`, `extract_transcript`, `has_leaked_markup`, `LEAK_MARKERS`
- Produces: `xkcd.apply_limit(items, limit)`, `xkcd.pending_explain_numbers(db, limit=None) -> list[int]`, `xkcd.store_explain(db, num, text, incomplete) -> None`, `xkcd.cmd_fetch_explain(args) -> int`; `comic_numbers` now delegates to `apply_limit`

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_limit_zero_means_none():
    """Review Focus 5: the same falsy-zero bug --limit 0 hit in `fetch`."""
    assert xkcd.apply_limit([1, 2, 3], 0) == []
    assert xkcd.apply_limit([1, 2, 3], None) == [1, 2, 3]
    assert xkcd.apply_limit([1, 2, 3], 2) == [1, 2]


def test_comic_numbers_still_honours_zero_after_delegating():
    assert xkcd.comic_numbers(10, 0) == []
    assert xkcd.comic_numbers(5, None) == [1, 2, 3, 4, 5]


def test_pending_explain_numbers_only_lists_comics_without_one():
    db = seeded_db()
    assert xkcd.pending_explain_numbers(db) == [2, 3]


def test_pending_explain_numbers_skips_already_fetched_rows():
    """Review Focus 4: a rerun must not re-fetch what it already has."""
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]", False)
    assert xkcd.pending_explain_numbers(db) == [3]


def test_pending_explain_numbers_retries_rows_that_never_succeeded():
    db = seeded_db()
    # num 2 and 3 are untouched, so both remain pending
    assert xkcd.pending_explain_numbers(db) == [2, 3]


def test_pending_explain_numbers_honours_limit_zero():
    db = seeded_db()
    assert xkcd.pending_explain_numbers(db, 0) == []


def test_store_explain_records_text_and_marks_it_fetched():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]", False)
    row = db.execute("SELECT * FROM comics WHERE num = 2").fetchone()
    assert row["explain_transcript"] == "[a scene]"
    assert row["explain_incomplete"] == 0
    assert row["explain_fetched_at"]


def test_store_explain_marks_an_empty_page_as_fetched():
    """Review Focus 3: an empty page is fetched-and-empty, not retried forever."""
    db = seeded_db()
    xkcd.store_explain(db, 2, "", False)
    row = db.execute("SELECT * FROM comics WHERE num = 2").fetchone()
    assert row["explain_transcript"] == ""
    assert row["explain_fetched_at"]
    assert xkcd.pending_explain_numbers(db) == [3]


def test_store_explain_records_the_incomplete_flag():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]", True)
    assert db.execute("SELECT explain_incomplete FROM comics WHERE num = 2").fetchone()[0] == 1


def test_cmd_fetch_explain_rejects_leaked_markup_instead_of_storing_it():
    """Review Focus 2 at the storage boundary."""
    db = seeded_db()
    page = EXPLAIN_PAGE.replace('<div style="clear: both">', "")   # boundary removed
    stored = xkcd.i_store_explain_page(db, 3, page)
    assert stored is False
    row = db.execute("SELECT * FROM comics WHERE num = 3").fetchone()
    assert not row["explain_fetched_at"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: `AttributeError: module 'xkcd' has no attribute 'apply_limit'`.

- [ ] **Step 3: Write the implementation**

Add the subcommand to `build_parser`, after the `fetch` block:

```python
    explain = sub.add_parser(
        "fetch-explain", help="fetch transcripts from explainxkcd for comics that lack one"
    )
    explain.add_argument("--limit", type=int, default=None,
                         help="stop after this many comics (for testing)")
    explain.add_argument("--delay", type=float, default=1.0,
                         help="seconds between requests; robots.txt asks for 1")
```

Replace `comic_numbers` with a version that shares the limit rule, and append the rest after `cmd_fetch`:

```python
def apply_limit(items, limit):
    """`limit=None` means all, `limit=0` means none.

    A truthiness check here is how `--limit 0` once started a full corpus fetch.
    """
    return list(items) if limit is None else list(items)[:limit]


def comic_numbers(latest_num, limit=None):
    """Comic numbers 1..latest, excluding the nonexistent #404."""
    return apply_limit((n for n in range(1, latest_num + 1) if n != 404), limit)


def pending_explain_numbers(db, limit=None):
    """Comics with no official transcript and no explainxkcd fetch recorded.

    `explain_fetched_at` is the marker, not the presence of text, so a page that
    legitimately has no Transcript section is not retried forever.
    """
    numbers = [
        row[0]
        for row in db.execute(
            "SELECT num FROM comics WHERE has_transcript = 0"
            " AND explain_fetched_at IS NULL ORDER BY num"
        )
    ]
    return apply_limit(numbers, limit)


def store_explain(db, num, text, incomplete):
    """Record a fetch attempt. `text` may be empty, which still counts as done."""
    db.execute(
        "UPDATE comics SET explain_transcript = ?, explain_fetched_at = ?,"
        " explain_incomplete = ? WHERE num = ?",
        (text, time.strftime("%Y-%m-%dT%H:%M:%S"), 1 if incomplete else 0, num),
    )
    db.commit()


def i_store_explain_page(db, num, page):
    """Extract and store one page's transcript. Returns False when the extracted
    text contains leaked Talk-page markup, in which case nothing is stored."""
    text, incomplete = extract_transcript(page)
    if has_leaked_markup(text):
        return False
    store_explain(db, num, text, incomplete)
    return True


def cmd_fetch_explain(args):
    db = connect()
    init_db(db)

    pending = pending_explain_numbers(db, args.limit)
    fetched = empty = failed = leaked = incomplete = 0
    failures = []

    for index, num in enumerate(pending, 1):
        try:
            page = fetch_explain_html(num)
        except Exception as exc:
            failures.append((num, f"fetch: {type(exc).__name__}"))
            failed += 1
            time.sleep(args.delay)
            continue

        text, is_incomplete = extract_transcript(page)
        if has_leaked_markup(text):
            failures.append((num, "leaked markup, not stored"))
            leaked += 1
        else:
            store_explain(db, num, text, is_incomplete)
            if text.strip():
                fetched += 1
                if is_incomplete:
                    incomplete += 1
            else:
                empty += 1

        if index % 50 == 0:
            print(f"  {index}/{len(pending)}  stored={fetched} empty={empty} failed={len(failures)}")
        time.sleep(args.delay)

    print(
        f"\nstored {fetched} ({incomplete} flagged incomplete), {empty} empty, "
        f"{len(failures)} failed"
    )
    for num, why in failures[:40]:
        print(f"  #{num}: {why}")
    if failures:
        print(f"  ... {len(failures)} total failures")
    return 1 if failures else 0
```

The `i_store_explain_page` name is deliberate: it is the tested seam that `cmd_fetch_explain`'s loop logic mirrors, so the leak-guard path can be exercised without a network.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `85/85 passed`

- [ ] **Step 5: Live check on five comics, then a resume check**

Run:

```bash
python3 xkcd.py fetch-explain --limit 5
echo "exit=$?"
python3 xkcd.py fetch-explain --limit 5
```

Expected: the first run reports `stored 5`, exit 0. The second reports `stored 0` because those rows are now fetched and skipped, which is Review Focus 4.

Then confirm nothing leaked and `--limit 0` is inert:

```bash
python3 - <<'PY' 2>/dev/null
import xkcd
db = xkcd.connect()
rows = db.execute("SELECT num, length(explain_transcript) n FROM comics WHERE explain_fetched_at IS NOT NULL ORDER BY num").fetchall()
print("fetched rows:", [(r["num"], r["n"]) for r in rows])
print("leaked:", [r["num"] for r in rows if xkcd.has_leaked_markup(
    db.execute("SELECT explain_transcript FROM comics WHERE num=?", (r["num"],)).fetchone()[0])])
PY
python3 xkcd.py fetch-explain --limit 0
```

Expected: five rows with non-zero lengths, `leaked: []`, and the `--limit 0` run reports `stored 0`.

- [ ] **Step 6: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(explain): add resumable fetch-explain with a leak guard"
```

---

### Task 4: Coalescing and analyze

**Files:**
- Modify: `xkcd.py` (`analyze_row`, `run_analyze`)
- Modify: `test_xkcd.py` (two existing fixtures gain a key; new tests added)

**Interfaces:**
- Consumes: `scene_blocks`, `dialogue_lines`, `speakers`, `is_interactive`
- Produces: `xkcd.STANDING_SINGLE_RE`, `xkcd.normalise_blocks(text) -> str`, `xkcd.coalesced_text(row) -> tuple[str, str]`; `analyze_row` now also returns `transcript_source`

- [ ] **Step 1: Write the failing tests**

Two existing fixtures must gain the new key, because `analyze_row` now reads it:

```python
ROW_WITH_TRANSCRIPT = {
    "num": 1, "title": "Barrel - Part 1", "alt": "Don't we all.",
    "transcript": COMIC_1, "img_url": "https://imgs.xkcd.com/comics/barrel_cropped_(1).jpg",
    "explain_transcript": None,
}
ROW_WITHOUT_TRANSCRIPT = {
    "num": 2198, "title": "Throw", "alt": "this calculator implements...",
    "transcript": "", "img_url": "https://imgs.xkcd.com/comics/throw.png",
    "explain_transcript": None,
}
```

New tests:

```python
ROW_EXPLAIN_ONLY = {
    "num": 1700, "title": "New Bug", "alt": "some alt",
    "transcript": "", "img_url": "https://imgs.xkcd.com/comics/new_bug.png",
    "explain_transcript": "[Megan is standing in front of a chart.]\n"
                         "Megan: Only two instruments remain.\n"
                         "Cueball: Which one do we lose?",
}


def test_normalise_blocks_converts_line_standing_single_brackets():
    assert xkcd.normalise_blocks("[a scene]\nMan: hi") == "[[a scene]]\nMan: hi"


def test_normalise_blocks_leaves_inline_and_double_brackets_alone():
    assert xkcd.normalise_blocks("Man: [[inline]] yes") == "Man: [[inline]] yes"
    assert xkcd.normalise_blocks("[[already]]") == "[[already]]"
    assert xkcd.normalise_blocks("Girl: [not a scene] inline") == "Girl: [not a scene] inline"


def test_coalesced_text_prefers_the_official_transcript():
    text, source = xkcd.coalesced_text(ROW_WITH_TRANSCRIPT)
    assert source == "official"
    assert "barrel" in text
    assert "Megan" not in text


def test_coalesced_text_falls_back_to_explainxkcd_and_normalises():
    text, source = xkcd.coalesced_text(ROW_EXPLAIN_ONLY)
    assert source == "explainxkcd"
    assert "[[" in text and "[Megan" not in text.replace("[[Megan", "")


def test_coalesced_text_reports_none_when_neither_exists():
    text, source = xkcd.coalesced_text(ROW_WITHOUT_TRANSCRIPT)
    assert text == ""
    assert source == "none"


def test_analyze_row_derives_features_from_an_explainxkcd_transcript():
    got = xkcd.analyze_row(ROW_EXPLAIN_ONLY)
    assert got["transcript_source"] == "explainxkcd"
    assert got["has_transcript"] == 1
    assert got["scene_blocks"] == 1
    assert got["dialogue_lines"] == 2
    assert json.loads(got["speakers"]) == ["Megan", "Cueball"]


def test_analyze_row_records_official_as_the_source():
    assert xkcd.analyze_row(ROW_WITH_TRANSCRIPT)["transcript_source"] == "official"


def test_analyze_row_records_none_and_nulls_when_no_source_exists():
    got = xkcd.analyze_row(ROW_WITHOUT_TRANSCRIPT)
    assert got["transcript_source"] == "none"
    assert got["scene_blocks"] is None


def test_run_analyze_covers_a_comic_with_only_an_explainxkcd_transcript():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]\nMan: hello", False)
    xkcd.run_analyze(db)
    row = db.execute("SELECT * FROM comics WHERE num = 2").fetchone()
    assert row["transcript_source"] == "explainxkcd"
    assert row["scene_blocks"] == 1
    assert db.execute(
        'SELECT COUNT(*) c FROM comics_fts WHERE comics_fts MATCH \'"scene"\''
    ).fetchone()["c"] == 1
```

The final assertion matters: the search index is built from `comics.transcript`, which is empty for explainxkcd-only rows, so the index must be rebuilt from the coalesced text instead.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: `AttributeError: module 'xkcd' has no attribute 'normalise_blocks'`, and the two edited fixtures raise `KeyError: 'explain_transcript'` until the implementation lands.

- [ ] **Step 3: Write the implementation**

Append after `rebuild_fts` and replace `analyze_row`:

```python
# explainxkcd writes a line-standing scene as [scene]; xkcd uses [[scene]].
STANDING_SINGLE_RE = re.compile(r"(?m)^[ \t]*\[(?!\[)(.*?)\][ \t]*$")


def normalise_blocks(text):
    """Rewrite explainxkcd's line-standing [scene] to xkcd's [[scene]].

    Applied only to text from explainxkcd, so scene_blocks() and its tests stay
    unchanged and the line-standing rule keeps one definition.
    """
    return STANDING_SINGLE_RE.sub(lambda m: f"[[{m.group(1)}]]", text or "")


def coalesced_text(row):
    """(text, source) for a comic. Official xkcd text wins; explainxkcd is the
    fallback. The sources are never merged into one string."""
    if (row["transcript"] or "").strip():
        return row["transcript"], "official"
    explain = (row["explain_transcript"] or "").strip()
    if explain:
        return normalise_blocks(explain), "explainxkcd"
    return "", "none"


def analyze_row(row):
    """Derived fields for one comic, from whichever transcript source exists.
    Text fields are None when there is no source, never 0."""
    text, source = coalesced_text(row)
    has_transcript = 1 if text.strip() else 0

    if has_transcript:
        scene = len(scene_blocks(text))
        dialogue = dialogue_lines(text)
        speaker_json = json.dumps(speakers(text))
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
        "transcript_source": source,
    }
```

Update `run_analyze`'s SELECT and UPDATE:

```python
    rows = db.execute(
        "SELECT num, title, alt, transcript, explain_transcript, img_url"
        " FROM comics ORDER BY num"
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
            alt_len = :alt_len,
            transcript_source = :transcript_source
        WHERE num = :num
        """,
        [analyze_row(row) for row in rows],
    )
```

And rebuild the index from the coalesced text, since an explainxkcd-only comic has an empty `transcript` column:

```python
def rebuild_fts(db):
    """Rebuild the search index from whichever transcript source each row has."""
    db.execute("DELETE FROM comics_fts")
    db.executemany(
        "INSERT INTO comics_fts (num, title, alt, transcript) VALUES (?, ?, ?, ?)",
        (
            (row["num"], row["title"], row["alt"] or "", coalesced_text(row)[0])
            for row in db.execute(
                "SELECT num, title, alt, transcript, explain_transcript FROM comics"
            )
        ),
    )
    db.commit()
```

`rebuild_fts` now runs after the updates in `run_analyze`, and `run_analyze` must pass `explain_transcript` in the row it inspects.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `94/94 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(analyze): derive features from coalesced transcripts"
```

---

### Task 5: Split statistics by source

**Files:**
- Modify: `xkcd.py` (`corpus_stats`, `format_stats`)
- Modify: `test_xkcd.py` (the seeded_db helper and the speaker assertions)

**Interfaces:**
- Consumes: `transcript_source`
- Produces: `corpus_stats` returns `speakers_by_source` and `transcript_sources` and `incomplete_count`, and no longer returns a pooled `top_speakers`

- [ ] **Step 1: Write the failing tests**

The existing `seeded_db` helper already produces one official and two transcript-less rows. Update the three assertions that referenced `top_speakers`:

```python
def test_corpus_stats_counts_each_transcript_source():
    s = xkcd.corpus_stats(seeded_db())
    assert s["transcript_sources"]["official"] == 1
    assert s["transcript_sources"]["explainxkcd"] == 0
    assert s["transcript_sources"]["none"] == 2


def test_corpus_stats_never_pools_speakers_across_sources():
    """The spec's rule: Man (official) and Megan (explainxkcd) are different
    conventions and must not be added together."""
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]\nMan: hello", False)
    xkcd.run_analyze(db)
    s = xkcd.corpus_stats(db)
    assert s["speakers_by_source"]["official"][0] == ("Boy", 1)
    assert ("Boy", 1) not in s["speakers_by_source"]["explainxkcd"]
    assert "top_speakers" not in s


def test_corpus_stats_reports_the_incomplete_count():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]\nMan: hello", True)
    xkcd.run_analyze(db)
    assert xkcd.corpus_stats(db)["incomplete_count"] == 1


def test_format_stats_prints_the_sources_separately():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]\nMan: hello", False)
    xkcd.run_analyze(db)
    text = xkcd.format_stats(xkcd.corpus_stats(db))
    assert "official" in text
    assert "explainxkcd" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: `KeyError: 'transcript_sources'` and the old `test_corpus_stats_top_speakers_ignores_transcript_less_rows` failing on the new shape.

- [ ] **Step 3: Write the implementation**

Replace the speaker aggregation and return block inside `corpus_stats`:

```python
    speakers_by_source = {"official": collections.Counter(), "explainxkcd": collections.Counter()}
    for row in db.execute(
        "SELECT speakers, transcript_source FROM comics WHERE speakers IS NOT NULL"
    ):
        bucket = speakers_by_source.get(row["transcript_source"])
        if bucket is None:
            continue
        for name in json.loads(row["speakers"]):
            bucket[name] += 1

    transcript_sources = {"official": 0, "explainxkcd": 0, "none": 0}
    for row in db.execute(
        "SELECT COALESCE(transcript_source, 'none') s, COUNT(*) c FROM comics GROUP BY s"
    ):
        transcript_sources[row["s"]] = row["c"]
```

and in the returned dict replace `"top_speakers": ...` with:

```python
        # Never pooled: the two sources use different naming conventions.
        "speakers_by_source": {
            source: counter.most_common(top)
            for source, counter in speakers_by_source.items()
        },
        "transcript_sources": transcript_sources,
        "incomplete_count": db.execute(
            "SELECT COUNT(*) c FROM comics WHERE explain_incomplete = 1"
        ).fetchone()["c"],
```

In `format_stats`, replace the speaker block and add a source block:

```python
    lines += ["", "transcript sources"]
    for source in ("official", "explainxkcd", "none"):
        lines.append(f"  {source:<12}         {s['transcript_sources'][source]}")
    if s["incomplete_count"]:
        lines.append(f"  flagged incomplete   {s['incomplete_count']}")
    for source in ("official", "explainxkcd"):
        entries = s["speakers_by_source"][source]
        if not entries:
            continue
        lines += ["", f"top speakers ({source})"]
        for name, count in entries:
            lines.append(f"  {count:>5}  {name}")
```

Delete the old `top speakers (of N transcripts)` block that used `s["top_speakers"]`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `98/98 passed`

- [ ] **Step 5: Verify against the live corpus**

Run:

```bash
python3 xkcd.py stats --top 8 2>/dev/null | sed -n '1,40p'
```

Expected: a `transcript sources` block showing `official 1665`, and `explainxkcd` at whatever the partial fetch has reached, plus separate `top speakers (official)` and `top speakers (explainxkcd)` lists. Nothing pooled.

- [ ] **Step 6: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(stats): split speaker counts by transcript source"
```

---

### Task 6: Label the source in evidence packs

**Files:**
- Modify: `xkcd.py` (`format_pack`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `corpus_stats`, `transcript_source`
- Produces: no signature change; `format_pack` output gains a source label per exemplar and per speaker list

- [ ] **Step 1: Write the failing tests**

```python
def test_format_pack_labels_each_exemplar_with_its_source():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]\nMan: hello", False)
    xkcd.run_analyze(db)
    text = xkcd.format_pack(db, "scene", xkcd.retrieve(db, "scene"))
    assert "[explainxkcd]" in text


def test_format_pack_labels_official_exemplars():
    db = seeded_db()
    text = xkcd.format_pack(db, "barrel", xkcd.retrieve(db, "barrel"))
    assert "[official]" in text


def test_format_pack_separates_the_two_speaker_lists():
    db = seeded_db()
    xkcd.store_explain(db, 2, "[a scene]\nMan: hello", False)
    xkcd.run_analyze(db)
    text = xkcd.format_pack(db, "barrel", xkcd.retrieve(db, "barrel"))
    assert "Speakers in official transcripts" in text
    assert "Speakers in explainxkcd transcripts" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: failures on the three new tests; `[official]` and `[explainxkcd]` are absent from the output.

- [ ] **Step 3: Write the implementation**

In `format_pack`, change the exemplar heading line and the speaker block:

```python
        for row in rows:
            source = row["transcript_source"] or "none"
            lines.append(f"### #{row['num']} {row['title']} ({row['date']}) [{source}]")
```

and replace the single `## Speakers in the corpus` tail with:

```python
    for source, label in (("official", "official"), ("explainxkcd", "explainxkcd")):
        entries = stats["speakers_by_source"][source]
        if not entries:
            continue
        lines.append(f"## Speakers in {label} transcripts")
        lines.append(", ".join(name for name, _ in entries))
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `101/101 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(pack): label each exemplar with its transcript source"
```

---

### Task 7: Selftest coverage checks

**Files:**
- Modify: `xkcd.py` (`run_selftest`)
- Modify: `test_xkcd.py`

**Interfaces:**
- Consumes: `has_leaked_markup`, `transcript_source`
- Produces: `xkcd.find_leaked_transcripts(db) -> list[int]`; `run_selftest` gains three checks and an incomplete-count line

- [ ] **Step 1: Write the failing test**

Test the helper directly rather than asserting on `run_selftest`'s aggregate exit code. The aggregate returns 1 for several unrelated reasons on a small fixture corpus, including the pinned `1665` transcript count, so a test asserting `run_selftest(db) == 1` would pass whether or not the new check exists. That is the same shape as the false-positive check this project already had to fix once.

```python
def test_find_leaked_transcripts_flags_only_the_leaking_row():
    """Review Focus 2, asserted precisely rather than through an exit code."""
    db = seeded_db()
    db.execute("UPDATE comics SET explain_transcript = 'Add comment',"
               " explain_fetched_at = 'now' WHERE num = 2")
    db.commit()
    assert xkcd.find_leaked_transcripts(db) == [2]


def test_find_leaked_transcripts_is_empty_on_clean_data():
    db = seeded_db()
    assert xkcd.find_leaked_transcripts(db) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 test_xkcd.py`
Expected: `AttributeError: module 'xkcd' has no attribute 'find_leaked_transcripts'`.

- [ ] **Step 3: Write the implementation**

Add the helper above `run_selftest`:

```python
def find_leaked_transcripts(db):
    """Comic numbers whose stored explainxkcd text contains Talk-page markup.

    Twelve probes cannot prove the extractor across 1636 pages, so this runs as
    a check over the whole corpus after every fetch.
    """
    return [
        row["num"]
        for row in db.execute("SELECT num, explain_transcript FROM comics")
        if has_leaked_markup(row["explain_transcript"])
    ]
```

Add three checks inside `run_selftest`, before the final reporting block:

```python
    check("no Talk-page markup leaked into any transcript",
          find_leaked_transcripts(db), [])

    unsourced = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE COALESCE(transcript_source, 'none') = 'none'"
    ).fetchone()["c"]
    check("every comic has a transcript source", unsourced, 0)

    missing_blocks = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE has_transcript = 1 AND scene_blocks IS NULL"
    ).fetchone()["c"]
    check("every sourced transcript has scene-block data", missing_blocks, 0)
```

Add an incomplete count line to the printed output, without making it a pass/fail check, since the wiki's count changes as editors work:

```python
    incomplete = db.execute(
        "SELECT COUNT(*) c FROM comics WHERE explain_incomplete = 1"
    ).fetchone()["c"]
    print(f"\nflagged incomplete by explainxkcd: {incomplete}")
```

If the full run in Task 8 finds comics with no source from either place, set the `unsourced` expectation to that measured number and note it beside the check.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 test_xkcd.py`
Expected: `101/101 passed`

- [ ] **Step 5: Commit**

```bash
git add xkcd.py test_xkcd.py
git commit -m "feat(selftest): verify coverage and leak-freedom across sources"
```

---

### Task 8: Fetch the full corpus

**Files:**
- Modify: `README.md`
- Modify: `docs/corpus-stats.txt`

**Interfaces:**
- Consumes: `fetch-explain`, `analyze`, `selftest`, `stats`
- Produces: populated `explain_transcript` columns for the 1636 comics that lack an official transcript

- [ ] **Step 1: Add attribution and the new command to the README**

Add to the command list:

```bash
python3 xkcd.py fetch-explain   # explainxkcd transcripts, ~1636 requests at 1/sec
```

Add a new section:

```markdown
## Attribution and licensing

Two sources, two licences.

- The comics, and xkcd's own titles, alt text, and transcripts, are by Randall
  Munroe and licensed CC BY-NC 2.5 (https://xkcd.com/license.html).
- Transcripts fetched by `fetch-explain` come from explain xkcd
  (https://www.explainxkcd.com) and are licensed CC BY-SA 3.0. Reusing them
  requires attribution to explain xkcd **and** sharing derivative work under the
  same licence.

This matters only if `data/` is published. It is gitignored by default, and
keeping the corpus local carries no obligation.
```

- [ ] **Step 2: Run the full fetch**

Run: `python3 xkcd.py fetch-explain`

Expected at the end: `stored ~1636, ... 0 failed` and exit 0. This takes roughly 28 minutes at the 1-second crawl delay. If failures are reported, re-run the same command: it resumes and retries only what is outstanding. Repeat until failures are 0.

- [ ] **Step 3: Analyse everything**

Run: `python3 xkcd.py analyze`

Expected: `analyzed 3301 comics: 3301 with a transcript, 0 without`. The `with a transcript` figure rising from 1665 to something near 3301 is the whole point of this work.

- [ ] **Step 4: Assert the invariants**

Run: `python3 xkcd.py selftest; echo "exit=$?"`

Expected: all checks pass, `exit=0`, including the three new ones. If `every comic has a transcript source` fails, count the unsourced rows, inspect a few by hand, and set the expectation to that measured number only if those pages genuinely have no Transcript section. Do not adjust the expectation to hide a parse failure.

- [ ] **Step 5: Verify at scale, which is where the extractor actually gets tested**

Run:

```bash
python3 - <<'PY' 2>/dev/null
import sqlite3, xkcd
db = xkcd.connect()
rows = db.execute("SELECT num, transcript_source, length(COALESCE(explain_transcript,'')) n,"
                  " explain_incomplete FROM comics ORDER BY num").fetchall()
leaked = [r["num"] for r in rows if xkcd.has_leaked_markup(
    db.execute("SELECT explain_transcript FROM comics WHERE num=?", (r["num"],)).fetchone()[0])]
src = {}
for r in rows: src[r["transcript_source"]] = src.get(r["transcript_source"], 0) + 1
lens = sorted(r["n"] for r in rows if r["transcript_source"] == "explainxkcd")
print("sources:", src)
print("leaked rows:", leaked)
print("incomplete flagged:", sum(1 for r in rows if r["explain_incomplete"] == 1))
print(f"explainxkcd length min={lens[0]} median={lens[len(lens)//2]} max={lens[-1]}")
assert not leaked, leaked
print("OK")
PY
```

Expected: `leaked rows: []`, `sources` showing roughly 1665 official plus the rest explainxkcd, and a plausible length spread with no zero-length explainxkcd entries. Twelve probes proved the extractor; this proves it on all 1636, which is Review Focus 2 at full scale. Print the min and max transcripts and read them to confirm they are transcripts and not wiki furniture.

- [ ] **Step 6: Regenerate the statistics**

Run: `python3 xkcd.py stats --top 25 2>/dev/null > docs/corpus-stats.txt && sed -n '1,20p' docs/corpus-stats.txt`

Expected: the source breakdown appears, and the transcript-derivable sections now cover the whole corpus. Read the first 20 lines to confirm the figures moved as expected.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/corpus-stats.txt
git commit -m "docs: record explainxkcd attribution and full-corpus statistics"
```

---

### Task 9: Update the style guide

**Files:**
- Modify: `.agents/skills/xkcd-write/references/style-guide.md`

**Interfaces:**
- Consumes: `stats`, `docs/corpus-stats.txt`
- Produces: an updated guide. No code.

- [ ] **Step 1: Gather the evidence**

Run and read:

```bash
python3 xkcd.py stats --top 25
python3 xkcd.py pack "existential" --n 6
python3 xkcd.py pack "programming" --n 6
```

- [ ] **Step 2: Rewrite the coverage warning**

Replace the "Read this first" section. The old text says structural claims are scoped to `#1..#1677` because half the corpus has no transcript. That is no longer true, and leaving it would make the guide understate its own evidence.

The new section must cover:

- Structural data now comes from two sources. Official xkcd transcripts cover `#1..#1677`. explainxkcd covers the rest.
- The two conventions differ and the guide must say how: xkcd labels speakers by role, explainxkcd names them.
- The writer follows role labels, matching xkcd's own published text. State that this is a deliberate choice not to copy the community convention.
- Speaker statistics are split by source in `stats` and are never pooled, because pooling would add two conventions together.

- [ ] **Step 3: Update the structure and speaker sections**

- The structure table's percentages must be recomputed from the new `docs/corpus-stats.txt`, since panel counts now cover far more comics. Replace the old figures rather than leaving both. State the population the numbers are drawn from.
- The speaker section keeps role labels as the rule and adds the explanationxkcd names as context: `Cueball` (2 official transcripts), `Megan` (1), `Black Hat` (4), against the explainxkcd convention of naming throughout. The rule stays as before.

- [ ] **Step 4: Verify every number**

Run:

```bash
grep -nE "[0-9]{2,}" .agents/skills/xkcd-write/references/style-guide.md
```

Check each number against `docs/corpus-stats.txt` or a pack output. Fix any that do not match. A guide with invented statistics is worse than no guide.

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/xkcd-write/references/style-guide.md
git commit -m "docs(skill): update the style guide for full transcript coverage"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task. Source and politeness to Task 3's default delay and Task 2's User-Agent. Extraction and the boundary list to Task 2. Schema to Task 1. Coalescing to Task 4. Keeping the output honest to Tasks 5 and 6. Attribution to Task 8. Error handling to Task 3. Verification to Tasks 1, 2, 3, 5, 7 and 8. The scope limit (only the 1636) is implemented by `pending_explain_numbers` selecting `has_transcript = 0`.

**Placeholders.** None. Every step carries real code, a real command, and an expected result.

**Type consistency.** Verified across tasks: `MIGRATIONS`, `migrate`, `_get_html`, `fetch_explain_html`, `extract_transcript`, `has_leaked_markup`, `apply_limit`, `pending_explain_numbers`, `store_explain`, `i_store_explain_page`, `cmd_fetch_explain`, `STANDING_SINGLE_RE`, `normalise_blocks`, `coalesced_text`, and the `transcript_source` field that flows from `analyze_row` into `corpus_stats`, `format_stats`, `format_pack`, and `run_selftest`. `coalesced_text` takes a row-like mapping and every caller passes either a `sqlite3.Row` selected with `explain_transcript` or one of the two updated dict fixtures.

**Test counts.** Per task: 4, 7, 10, 9, 4, 3, 2. Running totals: 63 before this plan, then 67, 74, 84, 93, 97, 100, 102. If a count does not match when you run it, the plan and the code have diverged; fix whichever is wrong before committing.

**Two changes to existing tests are intentional and load-bearing.** `ROW_WITH_TRANSCRIPT` and `ROW_WITHOUT_TRANSCRIPT` gain an `explain_transcript` key because `analyze_row` now reads it, and the `top_speakers` assertions are replaced because the spec forbids pooling. Both are called out in their tasks.

**Review Focus coverage.** Item 1 (in-place migration) by `test_migrate_adds_columns_to_an_existing_table` and `test_migrate_preserves_existing_rows` in Task 1, plus the live check on the real 3301-row database. Item 2 (Talk-section leak) by `test_extract_transcript_does_not_leak_the_talk_section` and `test_cmd_fetch_explain_rejects_leaked_markup_instead_of_storing_it`, plus the full-corpus scan in Task 8 Step 5. Item 3 (no Transcript section) by `test_extract_transcript_returns_empty_when_there_is_no_section` and `test_store_explain_marks_an_empty_page_as_fetched`. Item 4 (partial-run resume) by `test_pending_explain_numbers_skips_already_fetched_rows` and the live resume check in Task 3 Step 5. Item 5 (`--limit 0`) by `test_apply_limit_zero_means_none` and `test_pending_explain_numbers_honours_limit_zero`.

**One weak step, flagged rather than hidden.** Task 7 step 1 tests `find_leaked_transcripts` directly instead of asserting on `run_selftest`'s exit code. The aggregate exits 1 for several unrelated reasons on a three-comic fixture, including the pinned `1665` transcript count, so an aggregate assertion would pass whether or not the new check exists. That is the same false-positive shape as the `LIKE '%Title text%'` check this project already had to fix. The selftest's own behaviour is verified instead by the real corpus run in Task 8 Step 4.
