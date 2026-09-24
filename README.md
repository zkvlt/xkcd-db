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
