# xkcd corpus

A local archive of every xkcd comic, plus a skill that writes new ones.

## Rebuild the corpus

```bash
python3 xkcd.py fetch           # ~3300 metadata + image requests, ~60 minutes
python3 xkcd.py fetch-explain   # explainxkcd transcripts, ~1636 requests at 1/sec
python3 xkcd.py analyze         # derive text features, seconds
python3 xkcd.py selftest        # assert the invariants, seconds
python3 xkcd.py stats           # print corpus aggregates
python3 xkcd.py pack "gardening"   # retrieve exemplars for a topic
```

`data/` is gitignored. It is reproducible output, roughly 170MB of images plus
the database.

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

3301 comics, in two halves by where the transcript comes from.

xkcd publishes a transcript in its own JSON for 1665 comics, and stopped after
`#1677`. Those use role labels for speakers (`Man`, `Woman`, `Person 1`).

The remaining 1636 have no transcript from xkcd, so `fetch-explain` fills the
gap from explain xkcd, which uses single-bracket scene blocks and names its
characters (`Cueball`, `Megan`).

The two are stored separately, never merged, and statistics that depend on them
are reported per source. See `docs/corpus-stats.txt` for the current figures.

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

`fetch-explain` reads article pages only. `robots.txt` disallows the MediaWiki
API, so the API is not used, and requests are serialised at one per second to
match the site's stated crawl delay.
