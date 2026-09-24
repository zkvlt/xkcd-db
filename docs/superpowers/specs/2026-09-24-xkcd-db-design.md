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
2. The derived analysis fields are populated wherever the source text supports
   them, left null where it does not, and the aggregate stats are real numbers
   rather than claims.
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

## Corpus facts measured during planning

All 3301 comics were probed before this spec was amended. Zero requests failed.
These numbers are measurements, not estimates, and they changed the design.

| Fact | Value |
| --- | --- |
| Comics that exist | 3301 (`#404` is absent) |
| Latest | `#3302` |
| With a non-empty transcript | **1665 (50.4%)** |
| Without any transcript | **1636** |
| Last comic with a transcript | `#1677` |
| With alt text | 3298 (three empties) |
| Alt text length (median / p90 / max) | 115 / 209 / 816 characters |
| Title length (median / p90 / max) | 13 / 22 / 53 characters |

Transcripts stopped being published around 2016. Everything from `#1678` onward
is empty, and eleven comics between `#1609` and `#1677` are missing one too.

This reshapes the analysis in three ways.

Derived text features exist for half the corpus and are null for the other half.
Every statistic that depends on transcript text is a statement about `#1` to
`#1677` only, and the `stats` output says so rather than reporting a corpus-wide
figure it cannot support.

Title and alt text are the only stylistic text available for all 3301 comics, and
alt text is the single most xkcd-specific writing in the corpus. The writer leans
on title and alt pairs, not on transcripts.

Scene blocks are not panels. See the transcript conventions below.

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
| `scene_blocks` | count of `[[...]]` scene blocks, null when there is no transcript |
| `dialogue_lines` | count of `Speaker: line` occurrences, null when there is no transcript |
| `characters` | JSON array of names found inside `[[...]]`, null when there is no transcript |
| `speakers` | JSON array of names followed by a colon, null when there is no transcript |
| `topics` | JSON array of taxonomy tags, computed for every comic |
| `has_transcript` | boolean |
| `is_interactive` | boolean |
| `title_len`, `alt_len` | character counts, computed for every comic |

`comics_fts` is an FTS5 table over `title`, `alt`, and `transcript`, using
`tokenize='porter unicode61'` so "running" matches "run". `num` is stored
unindexed and used to join back.

### Transcript conventions

Transcripts are hand-written, inconsistent, and only exist for the first half of
the corpus. The parser handles all of the following, because all of it appears in
real data.

- `[[...]]` marks a scene description. It also appears inline inside dialogue, as
  in `Girl: [[arms in the air]] Ohmygod, mine too!`, so an inline occurrence is a
  stage direction rather than a new panel.
- `((...))` marks an author note about the comic. Present in 178 transcripts.
- `{{...}}` embeds metadata, most often the alt text. Present in 1621 of 1665
  transcripts, with measured labels: `title text` (1344), `alt text` (94), `alt`
  (75), `alt-text` (48), `title-text` (20), `title` (11), `panel title` (4),
  `headline` (3), `mouseover text` (2), `rollover text` (2), `legend` (1).
- Stripping `{{...}}` and `((...))` is necessary but not sufficient. Comic `#487`
  opens with a bare `Title text: XKCD presents a guide to numerical sex
  positions:` outside any braces. A metadata label blocklist is therefore applied
  after stripping, so no label matching `title`, `alt`, `mouseover`, `rollover`,
  `subheading`, `headline`, `legend`, `panel title`, `citation`, `footnote`,
  `author's comment`, or `options` can be recorded as a speaker. `Caption` is
  deliberately not excluded, since a caption drawn inside a panel is part of the
  comic.
- Dialogue is `Speaker: line`, and a line can continue over several lines.
- Named characters are used inconsistently. `Black Hat`, `White Hat`, and
  `Beret Guy` appear, but `Cueball` and `Megan` appear in no transcript sampled.
  The most common speakers are `Man`, `Woman`, `Person 1`, `Person`, `Girl`,
  `Person 2`, `Narrator`, and `Figure`, which are positional labels rather than
  characters. Speaker extraction stays generic and no fixed roster is assumed.
- **187 of 1665 transcripts contain no `[[...]]` block at all.** Scene-block
  count is therefore null-safe and frequently zero, and it is reported as scene
  blocks rather than panels. Median across the corpus is 1, maximum is 87.

Comic `#1` is the canonical fixture: two scene blocks, `Boy` as the only speaker,
and an alt text of `Don't we all.` Comic `#300` is the stage-direction fixture:
one scene block, even though its dialogue line reads
`Girl: [[arms in the air]] Ohmygod, mine too!`

### Data flow

**`fetch`** probes `https://xkcd.com/info.0.json` for the latest number, then
walks `1..latest`. It skips `#404`, which does not exist. For each number it
gets `info.0.json`, downloads the image when it is absent from disk, and
inserts the raw row. Existing rows and existing images are skipped, so the
command is safe to interrupt and rerun.

**`analyze`** walks every row and computes the derived fields from stored text.
Pure functions, no I/O beyond the database, so it is cheap to rerun.

**`stats`** prints aggregates: date range, scene-block distribution, top
speakers, topic counts, transcript coverage, title and alt length percentiles,
and the most frequent content words after stopword removal. Any figure that
depends on transcript text is labelled with the 1665-comic coverage it is drawn
from.

**`pack <topic>`** takes the union of two retrievals: exact taxonomy tag matches,
and FTS5 BM25 hits over title, alt, and transcript. It returns the top eight
exemplars with their transcripts, plus the corpus-wide speaker roster and the
topic's corpus stats.

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
  `has_transcript` to false. This is the normal state for 1636 of 3301 comics,
  not an error. Every derived text field stays null for those rows, in
  particular `scene_blocks`, so corpus aggregates cannot be distorted by 1636
  phantom zeros.
- Existing rows and existing images are skipped, which makes every command
  idempotent.

## Known special cases

- `#404` does not exist. Skipping it is required, not defensive.
- The transcript is absent from `#1678` onward, and from eleven comics between
  `#1609` and `#1677`. Half the corpus is title-and-alt only.
- 187 transcripts contain no `[[...]]` block, so zero scene blocks is a valid
  result rather than a parse failure.
- `{{...}}` metadata blocks sit inside the transcript and look like dialogue to a
  naive `Name:` regex. They must be stripped first.
- Some comics carry an undocumented `extra_parts` key, seen on `#2198`. Unknown
  keys are ignored rather than treated as errors.
- Interactive comics (`1608`, `1416`, `1110`, `1525`, and similar) ship
  JavaScript or animation rather than a static panel. They are flagged
  `is_interactive` and excluded from scene-block statistics.
- Images are a mix of `.png` and `.jpg`, with some `.gif`.
- Image filenames contain parentheses and unicode, so URLs need encoding rather
  than string concatenation.
- `#3302` is the current latest. The number grows over time, which is why
  `fetch` probes for it instead of hardcoding.

## Testing

`test_xkcd.py` holds assert-based tests over the pure functions, using fixture
strings copied from real comics. No network access in tests. Covered: transcript
parsing, scene-block counting, `{{...}}` and `((...))` stripping, speaker and
character extraction, taxonomy tagging, the pack formatter, FTS query escaping,
and URL encoding of awkward filenames.

There is also `xkcd.py selftest`, which asserts against known-good data in the
live database: that comic `#1` parses to two scene blocks, the alt text
`Don't we all.`, and `Boy` as its only speaker; that comic `#300` parses to one
scene block and not two, because its second `[[...]]` is an inline stage
direction; that a transcript with no scene blocks yields zero rather than null
(187 of them do); and that a comic with no transcript yields null rather than
zero for every derived text field.

## Verification

Claims in this project are checked against real output, not asserted.

| Claim | Check |
| --- | --- |
| Every comic downloaded | Row count equals image count on disk equals distinct nums, minus known failures, with nothing zero-byte |
| Fetch covered the corpus | 3300 rows, one per existing comic, and `#404` absent |
| Analysis is real | Exactly 1665 rows have `has_transcript` true, and every one has a non-null `scene_blocks` value |
| Nulls are honest | Every one of the 1636 transcript-less rows has null, not zero, for all five derived text fields |
| Parsing is correct | Comic `#1` yields two scene blocks, the alt text `Don't we all.`, and `Boy` as its only speaker |
| Stage directions are not panels | Comic `#300` yields one scene block, not two |
| Metadata stripping works | `Title text` never appears in the `speakers` array of any row |
| Retrieval is relevant | `pack "gardening"` and `pack "databases"` return comics a human agrees fit |
| Retrieval is crash-proof | `pack` on a topic full of FTS5 metacharacters returns a result or a clean message, never a traceback |
| The writer works | Two or three comics written on topics absent from the corpus, reviewed for whether they read like xkcd |

## Scale

3301 comics exist, so the run is 3301 metadata requests plus 3301 image
requests. A nine-comic sample of image sizes came back with a median near 65KB,
which puts the full corpus at roughly 300 to 600MB on disk. Sequential with a
short delay puts the download at 20 to 40 minutes, which runs in the background.
Analysis, stats, and retrieval all complete in seconds.

Planning reconnaissance already fetched all 3301 metadata records with zero
failures, so the endpoint is reliable at this volume. Only the images remain
untested at scale.

## Open decisions already settled

- Scripts only, no rendered images.
- Text analysis only, no vision pass.
- SQLite plus FTS5, no embeddings.
- Pi skill using the session model, no separate API key.
- Both a database and a written style guide.
- Single `xkcd.py` CLI rather than a layered package.
