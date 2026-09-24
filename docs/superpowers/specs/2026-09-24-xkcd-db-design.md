# xkcd corpus database and comic writer

Date: 2026-09-24
Status: approved for planning
Repo: https://github.com/zkvlt/xkcd-db

## Purpose

Build a local, queryable corpus of every xkcd comic, analyse it, and use that
analysis to write new xkcd-style comics on topics xkcd never covered.

The corpus is the foundation. The writer is the payoff.

## Who this is for

One person (the repo owner) writing xkcd-style comics on demand. There is no
multi-user requirement, no service to host, and no build pipeline to wire up.

## Success criteria

1. Every comic that ships a static image is on disk, with metadata in the
   database, and the fetch is resumable.
2. The derived analysis fields are populated for the whole corpus, and the
   aggregate stats are real numbers rather than claims.
3. `pack "<topic>"` returns exemplar comics a human would agree are relevant to
   that topic.
4. The writer skill produces a comic script that reads like xkcd: a title, an
   alt text that lands a second joke, and a panel script in xkcd's own
   transcript convention, on a topic of the caller's choosing.

## Non-goals

- Rendering comic images. The writer produces scripts, not PNGs.
- Vision or image analysis. Analysis reads text only.
- Semantic search via embeddings. Retrieval is keyword and tag based.
- A hosted service, HTTP API, or UI.
- Fine-tuning any model.
- Publishing comics anywhere.

## Constraints

- Python 3.12, standard library preferred.
- SQLite for storage, with FTS5 for retrieval. Both are already available.
- `requests` is used for HTTP, since it is already installed.
- No new dependencies. No `sklearn`, no vector store, no API keys for the
  corpus pipeline.
- The writer uses the model already attached to the pi session. It must not
  require an API key of its own.
- Be polite to xkcd. Sequential requests with a small delay, and no
  parallelism.

Stack verified on this machine before the design was written: FTS5 available in
the system `sqlite3`, `numpy`/`pandas`/`requests`/`PIL` importable, `jq` and
`curl` present, 13GB free disk. xkcd's latest comic at design time is `#3302`.

## Ordering

Download everything first, then analyse. The user asked for this order
explicitly, and it is also the correct dependency order: analysis needs the
full corpus in hand, and the fetch is the slow, failure-prone step that should
finish completely before any derived work starts.

## Architecture

Three layers, each runnable on its own.

**Raw store.** `data/comics/<num>.<ext>` holds the image bytes. `data/xkcd.db`
holds one row per comic with the raw API fields. Nothing derived lives here.

**Derived layer.** The `analyze` command reads raw rows, computes features, and
writes them back into the same row in derived columns. Derivation is separated
from fetching so the analyzer can be rewritten and re-run without re-downloading
600MB of images.

**Consumption layer.** `stats` reports aggregates for humans. `pack` retrieves
exemplars and formats an evidence block. The writer skill calls `pack` and reads
the style guide.

### Layout

```
Code/xkcd/
  xkcd.py                          # fetch | analyze | stats | pack | selftest
  test_xkcd.py                     # assert-based tests, no network
  data/xkcd.db                     # gitignored
  data/comics/0001.jpg ...         # gitignored
  docs/superpowers/specs/          # this spec
  .agents/skills/xkcd-write/
    SKILL.md
    references/style-guide.md
```

`data/` is gitignored. The corpus is a build artifact, reproducible by running
`fetch`.

### Schema

Raw columns, written by `fetch`:

| column | notes |
| --- | --- |
| `num` | integer primary key |
| `title`, `safe_title`, `alt`, `transcript`, `news`, `link` | API text fields |
| `year`, `month`, `day` | stored as an ISO date string |
| `img_url` | remote URL |
| `img_path` | local relative path, null if the download failed |
| `img_bytes`, `img_width`, `img_height` | from the downloaded file |
| `fetched_at` | timestamp, so a stale row is detectable |

Derived columns, written by `analyze`, all nullable:

| column | notes |
| --- | --- |
| `panel_count` | count of `[[...]]` blocks |
| `dialogue_lines` | count of `Speaker: line` occurrences |
| `characters` | JSON array of names found inside `[[...]]` |
| `speakers` | JSON array of names followed by a colon |
| `topics` | JSON array of taxonomy tags |
| `has_transcript` | boolean |
| `is_interactive` | boolean |
| `title_len`, `alt_len` | character counts |

`comics_fts` is an FTS5 table over `title`, `alt`, and `transcript`, using
`tokenize='porter unicode61'` so "running" matches "run". `num` is stored
unindexed and used to join back.

### Data flow

**`fetch`** probes `https://xkcd.com/info.0.json` for the latest number, then
walks `1..latest`. It skips `#404`, which does not exist. For each number it
gets `info.0.json`, downloads the image when it is absent from disk, and
inserts the raw row. Existing rows and existing images are skipped, so the
command is safe to interrupt and rerun.

**`analyze`** walks every row and computes the derived fields from stored text.
Pure functions, no I/O beyond the database, so it is cheap to rerun.

**`stats`** prints aggregates: date range, panel distribution, top characters,
topic counts, transcript coverage, title and alt length percentiles, and the
most frequent content words after stopword removal.

**`pack <topic>`** takes the union of two retrievals: exact taxonomy tag matches,
and FTS5 BM25 hits over title, alt, and transcript. It returns the top eight
exemplars with their transcripts, plus the character roster and the topic's
corpus stats.

### Topic taxonomy

A hand-written dict in `xkcd.py` maps a tag to keyword rules. Initial tag set:

`math`, `physics`, `space`, `biology`, `chemistry`, `programming`, `computers`,
`ai`, `statistics`, `engineering`, `linguistics`, `philosophy`, `economics`,
`romance`, `sex`, `existential`, `time-travel`, `internet`, `social-media`,
`meta`, `history`, `maps`, `food`, `health`, `cats`, `parenting`, `work`,
`politics`, `climate`, `weather`.

Keyword rules alone would miss comics that never name their subject, and BM25
alone would miss topic affinity. Running both and taking the union covers the
gap without embeddings. Extending the taxonomy means editing one dict.

## Interfaces

### `xkcd.py`

```
xkcd.py fetch [--limit N] [--delay S]
xkcd.py analyze
xkcd.py stats [--top N]
xkcd.py pack <topic> [--n 8]
xkcd.py selftest
```

Exit codes: `0` success, `1` completed with recorded failures, `2` hard error.
`fetch` prints progress every 100 comics and a failure summary at the end.

### Writer output format

The writer emits exactly this, and nothing else:

```
Title: <title>
Alt: <alt text>

[[panel 1 scene description]]
Cueball: <line>
[[panel 2 scene description]]
```

Scene descriptions in double brackets and dialogue as `Speaker: line` match
xkcd's own transcript convention, which means published scripts can be compared
against the corpus directly.

## Error handling

- HTTP 5xx and 429 retry three times with exponential backoff. Anything still
  failing is logged, recorded as a row with a null `img_path`, and the run
  continues. One bad comic must never abort a 3300-comic fetch.
- Images download to `<path>.part` and are renamed on completion, so a partial
  file cannot be mistaken for a finished one.
- A zero-byte or unreadable image is reported in the end-of-run summary rather
  than silently accepted.
- A missing or empty transcript is stored as an empty string and sets
  `has_transcript` to false. Comics with no transcript are common rather than
  exceptional, so this is a normal state, not an error. The `analyze` run
  reports the exact count.
- Existing rows and existing images are skipped, which makes every command
  idempotent.

## Known special cases

- `#404` does not exist. Skipping it is required, not defensive.
- Interactive comics (`1608`, `1416`, `1110`, `1525`, and similar) ship
  JavaScript or animation rather than a static panel. They are flagged
  `is_interactive` and excluded from panel-count statistics.
- Images are a mix of `.png` and `.jpg`, with some `.gif`.
- Image filenames contain parentheses and unicode, so URLs need encoding rather
  than string concatenation.
- `#3302` is the current latest. The number grows over time, which is why
  `fetch` probes for it instead of hardcoding.

## Testing

`test_xkcd.py` holds assert-based tests over the pure functions, using fixture
strings copied from real comics. No network access in tests. Covered: transcript
parsing, panel counting, character and speaker extraction, taxonomy tagging, the
pack formatter, and URL encoding of awkward filenames.

There is also `xkcd.py selftest`, which asserts against known-good live data in
the database: that comic `#1` parses into the barrel script with the boy as a
speaker, and that every comic with a transcript has a nonzero `panel_count`.

## Verification

Claims in this project are checked against real output, not asserted.

| Claim | Check |
| --- | --- |
| Every comic downloaded | Row count equals image count on disk equals distinct nums, minus known failures, with nothing zero-byte |
| Analysis is real | `panel_count > 0` for every comic that ships a transcript |
| Parsing is correct | Comic `#1` yields the barrel scene, one panel, and the boy as speaker |
| Retrieval is relevant | `pack "gardening"` and `pack "databases"` return comics a human agrees fit |
| The writer works | Two or three comics written on topics absent from the corpus, reviewed for whether they read like xkcd |

## Scale

Roughly 3300 JSON requests plus 3300 image requests. A nine-comic sample of
image sizes came back with a median near 65KB, which puts the full corpus at
roughly 300 to 600MB on disk. Sequential with a short delay puts the download at
20 to 40 minutes, which runs in the background. Analysis, stats, and retrieval
all complete in seconds.

## Open decisions already settled

- Scripts only, no rendered images.
- Text analysis only, no vision pass.
- SQLite plus FTS5, no embeddings.
- Pi skill using the session model, no separate API key.
- Both a database and a written style guide.
- Single `xkcd.py` CLI rather than a layered package.
