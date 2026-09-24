# Full transcript coverage from explainxkcd

Date: 2026-09-25
Status: approved for planning
Repo: https://github.com/zkvlt/xkcd-db
Extends: docs/superpowers/specs/2026-09-24-xkcd-db-design.md

## Purpose

Give the corpus a transcript for every comic, not just the first half.

The original spec accepted that 1636 of 3301 comics have no transcript, because
that is what xkcd publishes. Structural analysis was therefore scoped to
`#1..#1677`. This adds a second, community-written source so panel counts,
dialogue shape, and scene descriptions cover the whole run.

## Why the gap exists

Verified directly, not assumed.

xkcd's `info.0.json` `transcript` field is byte-identical to a hidden
`<div id="transcript" style="display: none">` in the comic page's metadata block.
It is a hand-written description placed there for machines, with no toggle and no
JavaScript to reveal it. It went intermittent from `#1609` (2015-11-27), with 11
scattered gaps, and stopped entirely after `#1677` (2016-05-06). No announcement
exists: the `news` field is empty for every comic from `#1670` to `#1720`.

xkcd's own API documentation describes the field as containing "transcripts
(when available)", so the absence is documented behaviour rather than a fault.

## What was measured before designing

| Check | Result |
| --- | --- |
| explainxkcd coverage of transcript-less comics | Every comic probed from `#1609` to `#3302` has a Transcript section, including the latest |
| Character naming | explainxkcd names characters (Megan, Cueball, Ponytail, Hairy); xkcd's own text uses role labels (Man, Woman, Person 1) |
| Scene block syntax | explainxkcd uses single `[scene]`; xkcd uses double `[[scene]]` |
| Transcript quality flags | Some transcripts carry a "one of N incomplete transcripts" maintenance notice, claiming 36 in total |
| Extractor accuracy | 12 of 12 probes extracted with zero leaked markup, all terminating on the same boundary marker |
| Crawl rules | `robots.txt` disallows `/wiki/api.php`; article pages allowed with `Crawl-delay: 1` |
| Licensing | wiki text CC BY-SA 3.0; the comics themselves CC BY-NC 2.5 |

## Constraints

- **No MediaWiki API.** `robots.txt` contains `Disallow: /wiki/api.php`. The API
  answers requests, but answering is not permission. Article HTML only.
- **Single-threaded, one request per second**, matching `Crawl-delay: 1`. The
  site asks to "crawl gently" and this respects that.
- A User-Agent identifying the tool and its rate.
- No new dependencies. Standard library plus `requests`, as before.
- The existing `fetch` command and its tests are not modified.

## Scope

Only the 1636 comics with no official transcript. Full structural coverage is
achieved without re-fetching text already held, which keeps load on a
volunteer-run wiki to the minimum that meets the goal.

At one request per second this is roughly 28 minutes.

## Architecture

One new command, `fetch-explain`, writing to three new columns. Derivation stays
in `analyze`, where it already lives.

### Command

```
xkcd.py fetch-explain [--limit N] [--delay S]
```

Resumable. Rows that already hold an `explain_transcript` are skipped, so an
interrupted run continues rather than restarting. A page that fails is recorded
in the failure summary and the run continues, matching `fetch`. Exit codes follow
the existing convention: `0` clean, `1` completed with failures, `2` hard error.

### Extraction

Locate the `Transcript` heading, then take content up to the first of:

```
<div style="clear: both">
<span id="discussion">
<h1
<div id="catlinks">
<div class="printfooter">
```

All 12 validation probes terminated on `<div style="clear: both">`. The other
markers are fallbacks for pages where that one is absent.

Then: convert block-level closers (`</p>`, `</div>`, `</li>`, `</ul>`, `</ol>`,
`</dd>`, `</dt>`, `</dl>`) and `<br>` to newlines, strip remaining tags, unescape
HTML entities, and trim trailing whitespace per line.

Finally strip the maintenance notice and set a flag. The notice reads
`This is one of N incomplete transcripts:` followed by a sentence asking editors
not to remove it too soon.

**Why the boundary list is load-bearing.** The raw page inlines the entire Talk
section after the transcript. A first attempt terminated only on `<h2>` and the
`printfooter` div, and for `#1700` it returned 16,507 characters of which the
real transcript was 951. Five of ten probes leaked discussion text. The boundary
list above is the fix, and the leak guard below is what proves it held.

### Schema

Three columns on `comics`, all nullable so "never fetched" is distinguishable
from "fetched and empty":

| column | meaning |
| --- | --- |
| `explain_transcript` | the extracted text, null when not fetched |
| `explain_fetched_at` | timestamp of a successful fetch |
| `explain_incomplete` | null when not fetched, 0 when complete, 1 when the notice was present |

Plus one derived column, written by `analyze` alongside the existing derived
fields:

| column | meaning |
| --- | --- |
| `transcript_source` | `official`, `explainxkcd`, or `none` |

`transcript_source` is derived rather than written by the fetch, so it stays
consistent with the same recompute-everything pattern the other derived fields
use.

### Coalescing

```python
def coalesced_text(row):
    """(text, source). Official xkcd text wins; explainxkcd is the fallback."""
```

Official text is preferred because it is xkcd's own wording and carries no
attribution obligation beyond the comic's own licence.

Scene-block syntax is normalised at coalesce time: a line-standing `[x]` from
explainxkcd becomes `[[x]]`. This keeps `scene_blocks()` and its existing tests
unchanged, and applies the same line-standing rule already used to distinguish
scene descriptions from inline stage directions.

`analyze` then derives `scene_blocks`, `dialogue_lines`, and `speakers` from the
coalesced text plus `transcript_source`. Structural coverage rises from 1665
comics to every comic that has either source.

### Keeping the output honest

Pooling the two sources would silently mix conventions, so:

- `stats` reports speaker counts **split by `transcript_source`**, never pooled.
  `Man` from official transcripts and `Megan` from explainxkcd are different
  conventions and must not be added together.
- `stats` reports the transcript-source breakdown and the incomplete count.
- `format_pack` labels every exemplar with its source.
- The style guide keeps role labels as the writer's rule and states plainly that
  the community source names characters and that this is deliberate, since the
  writer's output is an xkcd script rather than a wiki entry.

## Attribution

The two sources carry different licences and the README must say so:

- xkcd comic text: CC BY-NC 2.5, per xkcd.com/license.html
- explainxkcd wiki text: CC BY-SA 3.0, which requires attribution and share-alike

`data/` remains gitignored, so this changes nothing unless the corpus is
published. If it is, the explainxkcd-derived portion carries both obligations.

## Error handling

- One request per second, honoring `robots.txt`.
- A page with no Transcript section is recorded as fetched, with an empty
  `explain_transcript` and `explain_incomplete` set to 0, and counted. It is not
  retried forever. `explain_fetched_at` is the authoritative "was this row
  fetched" marker; `explain_incomplete` only records whether the maintenance
  notice was present in a section that did exist.
- Network failures retry with backoff using the existing `request_json` shape,
  then land in the failure summary.
- A `--limit` of `0` must fetch nothing, matching the fix already applied to
  `fetch`.

## Verification

| Claim | Check |
| --- | --- |
| Coverage | Every row has a `transcript_source` other than `none`, or is in a counted and reported remainder |
| No leaked markup | No stored `explain_transcript` contains `Add comment`, `Create topic`, `Retrieved from`, `Category:`, or `Privacy policy` |
| Incomplete flag works | The count of `explain_incomplete = 1` is reported and compared against the notice's claim of 36 |
| Extraction is not length-blind | The shortest and longest stored transcripts are printed and inspected by hand |
| Structural coverage is real | `scene_blocks` is non-null for every row that has any transcript, not just the official ones |
| Retrieval reaches the second half | A topic that previously returned nothing now returns exemplars, with sources labelled |
| The suite still passes | `python3 test_xkcd.py` is green and `selftest` reports more checks than before |
| Actual cost | Fetch wall-clock time and row count reported, against the 28-minute estimate |

## Non-goals

- Replacing or modifying the official transcripts. They stay authoritative for
  the comics that have them.
- Fetching the 1665 comics that already have an official transcript.
- Using the explainxkcd prose explanations, only the Transcript sections.
- Rendering images, or anything else from the original spec's non-goals.
