# xkcd style guide

Derived from the 3301-comic corpus in `data/xkcd.db`. Every number here is
measured, and the command that produced it is named so you can re-check it.

Regenerate the raw figures with `python3 xkcd.py stats --top 25`.

## Read this first: where the corpus comes from

The corpus covers 3301 comics, dated 2006-01-01 to 2026-09-23, and the
structural evidence now spans nearly all of it.

Transcripts come from two sources, and they are not the same kind of text.

| | comics | scene blocks | speakers |
| --- | --- | --- | --- |
| xkcd's own, up to `#1677` | 1665 | `[[like this]]` | role labels |
| explain xkcd | 1635 | `[like this]` | character names |
| neither | 1 | | |

xkcd publishes a transcript in its own JSON and stopped after `#1677`. The rest
come from the explain xkcd wiki, which writes in a different style: single
brackets for scenes, and characters named rather than described.

**This guide follows xkcd's own convention.** The writer's output is an xkcd
script, so it uses role labels and double brackets. Say the explain xkcd source
if you are looking at it and need to remember which is which.

The corpus is honest about which is which: `stats` reports every speaker count
separately per source, never combined, and `pack` labels each exemplar
`[official]` or `[explainxkcd]`. A combined speaker list would mix `Man` with
`Megan` and describe neither.

Title and alt text exist for 3298 of 3301 comics and span the entire run. When
the two sources disagree about structure, trust the title-and-alt evidence,
which does not depend on either.

## Length

| | min | median | p90 | max |
| --- | --- | --- | --- | --- |
| Title | 1 | 13 | 22 | 53 |
| Alt text | 0 | 115 | 209 | 816 |

Titles are short. A 13-character median means most titles are two or three
words. Anything past 22 characters puts you in the longest 10%.

Alt text is roughly ten times longer than the title. Aim for 40 to 200
characters, which is where the bulk of the corpus sits. 330 comics run past 209
characters, so a long alt is legitimate, but it has to earn the length by
continuing to be funny.

The alt text is empty on exactly three comics: `#1193`, `#1506`, `#1525`.

## What the alt text actually does

This is the most distinctive writing in xkcd and the easiest to get wrong.

The alt is a second beat. It is never a summary of the panels. It works as one
of five moves, all observed in the corpus:

**An escalating tangent that leaves the comic behind.** The alt starts near the
subject and keeps going until it is somewhere else entirely. `#1363` (xkcd
Phone) lists fake product warnings until it reaches "Under certain
circumstances, wireless transmitter may control God." `#1246` (Pale Blue Dot)
begins with a Carl Sagan passage and turns into a recruitment pitch for a
soul-eating deity before formally requesting Congressional funding.

**A quote presented as the punchline.** The alt quotes a real historical
source, letting the past say something damning about the present. `#1227` (The
Pace of Modern Life) is a genuine 1883 John Harvey Kellogg passage complaining
that marriage is collapsing, which lands because it is indistinguishable from a
current complaint. `#1311` quotes an 1825 newspaper sneering at a postmaster.

**A single reaction beat.** Nothing but a sound or an emoticon. `#25` and `#76`
are both `:(`. `#82` and `#412` are both `...`. `#11` is `Awww.`, `#126` is
`Uh-oh.`, `#1663` is `Relax.`, `#393` is `RIP, Gary.` 35 comics have an alt
under 16 characters. Use this mode sparingly, and only when the panel already
carries the joke.

**A correction or a footnote.** The alt flags something wrong or adds a caveat.
`#1888` (Still in Use) ends with an exasperated dialogue exchange about not
understanding what is using the system resources.

**Wordplay on the title.** `#18` (Snapple) has the alt `Sn = tin`, reading the
brand name as a chemical formula.

## Structure

Panel counts come from line-standing scene blocks across the 3300 transcripts.
This counts scene descriptions, not panels, and the two sources describe panels
at different granularity: the maximum of 189 belongs to one long annotated
transcript, so treat this as a shape indicator rather than a precise panel count.

| Scene blocks | Comics |
| --- | --- |
| 0 | 236 |
| 1 | 986 |
| 2 | 642 |
| 3 | 401 |
| 4 | 470 |
| 5 or more | 565 |

**One to four blocks covers 76% of the corpus.** One block alone is 30%. The
most common xkcd shape remains a single scene-setting description followed by
dialogue, with the punchline arriving in the last line of speech.

Zero blocks is not a failure. 236 transcripts have no line-standing scene block
at all, because the scene description is inline in a dialogue line rather than
standing on its own.

The figure for xkcd's own 1665 transcripts alone is 74%, which is what this
guide reported before the wiki source was added. The two agree closely, so the
shape guidance did not change when coverage doubled.

## Speakers

**Use role labels. That is the rule this guide sets, and it is what xkcd's own
published transcripts do.** Across the 1665 official transcripts, the most
frequent speakers are:

```
231  Man            44  Guy
201  Woman          28  Caption
 82  Person 1       24  Boy
 71  Person         22  Voice
 70  Person 2       21  Man 1  /  Man 2
 64  Girl           19  Hat Guy  /  Friend
 57  Figure         12  Black hat guy
 55  Narrator       15  Computer  /  Character
```

`Person 1` and `Person 2` are positional labels for interchangeable speakers.
`Caption` is a legitimate speaker, because a caption drawn inside a panel is
part of the comic.

### The characters do have names, and this guide still does not use them

The explain xkcd source names characters throughout, which is why it is stored
separately and counted separately. Across its 1635 transcripts the most frequent
speakers are `Cueball` (606), `Megan` (274), `Ponytail` (220), `White Hat`
(105), `Hairy` (59), `Miss Lenhart` (47), `Black Hat` (46), `Hairbun` (34), and
`Beret Guy` (29).

So the cast exists and readers recognise it. This guide still writes `Man` and
`Person 1`, for one reason: xkcd's own text does, and the script is meant to
read like xkcd's text rather than like the wiki's description of it. If you
would rather name them, the list above is the established cast, and using it is
a defensible choice. Just do not invent a name: there is no `Alice` or `Bob` in
this comic.

An earlier version of this guide claimed `Cueball` and `Megan` appeared nowhere
in the corpus. That was wrong, and it came from sampling a few comics instead of
searching all of them. Both names are in fact used as speakers in the official
transcripts too, rarely: `Cueball` in 2 (`#1324`, `#1486`), `Megan` in 1
(`#478`), `Black Hat` in 4 (`#146`, `#1136`, `#1137`, `#1321`).

### The visual cast, as the official transcripts describe it

The hat character appears as `Hat Guy` (19), `Hat guy` (10), `Black hat guy`
(12), and `Black Hat` (4), 45 occurrences in total. `Beret guy` appears 11 times.
These describe the drawing rather than name a person, which is the whole
convention in miniature.

## Topics

Counts are recall figures: a comic counts toward a topic if any of the topic's
synonyms appears anywhere in its title, alt text, or transcript, so these
overcount. They indicate which subjects have depth, not exact totals.

```
570  computers      142  parenting      74  cats
569  meta           139  engineering    70  weather
544  work           137  history        53  economics
459  space          131  existential    42  climate
272  internet       120  biology        27  philosophy
250  statistics     118  programming
237  physics        103  linguistics
197  romance        103  sex
185  math            94  time-travel
175  health          85  chemistry
167  food            83  gardening
160  maps            79  ai
159  politics
154  social-media
```

One caveat introduced by full coverage. These counts now include explain xkcd's
descriptive prose, and that prose is written *about* comics: it says "panel",
"comic", and "caption" constantly. The `meta` bucket therefore reads 569, up
from 254 when only xkcd's own text was counted, and much of that rise is the
source describing itself rather than a real shift in what xkcd writes about.
Read `meta` with that in mind. The other subjects are less affected, since a
comic about physics is described with physics words either way.

Subjects with real depth: computing, work and office life, space, physics,
mathematics and statistics, romance and relationships, and the self-referential
`meta` bucket.

Subjects with the least depth: philosophy (27), climate (42), economics (53).
A comic about any of those is still close to unexplored, and all three offer
room that the corpus itself shows is thin.

## Recurring devices

All confirmed against exemplar packs from `python3 xkcd.py pack "<topic>"`.

**The list that will not stop.** A comic sets up an enumeration and keeps
adding entries past the point of sense. `#1189` (Voyager 1) lists fake
boundaries the probe has crossed, reaching a "US Census Bureau Solar System
statistical boundary". `#2043` (Boathouses and Houseboats) compounds a
word-formation rule until it arrives at "bananaphones".

**A chart or diagram used as the argument.** `#231` (Cat Proximity) plots
"human proximity to cat" on an axis and lets the shape of the graph make the
joke. `#482` (Height) and `#256` (Online Communities) are annotated maps with
labelled regions, which is why their transcripts contain speakers like
`Map Title Text` and `Sea Area Labels`.

**Adopting a real-world format and playing it straight.** `#1446` (Landing)
is written as a live blog covering an unfolding spacecraft landing, with the
alt text no more than `[LIVE]`. `#2198` (Throw) is a ballistics calculator
applied to throwing something.

**The alt text is the entire punchline.** `#45` (Schrodinger) has the alt
`There was no alt-text until you moused over`. `#442` has `I love the
title-text!`. `#78` (Garfield) uses fair-use legal boilerplate as its alt. In
these the panels set up the situation and the alt carries the joke alone.

**Programming treated as an everyday problem.** `#353` (Python) opens with one
character floating in the air because he learned the language. `#292` (goto)
has a man at a computer weighing a data structure against a single `GOTO`.

**Misdirection that recontextualises the whole strip.** `#1100` (Vows) opens as
a wedding and turns out to be a football play. The alt, `So, um. Do you want to
get a drink after the game?`, confirms the reframe after the reader has already
committed to the first reading.

## Anti-patterns

Things the corpus never does.

**The alt text never summarises the panels.** The alt extends or subverts the
comic. If your alt would work as a caption for what happened, it is the wrong
alt. This is stated as a rule about the form; the evidence is the 3298 alts
themselves, all of which make a second move rather than describing the first.

**xkcd's own transcripts never name their speakers.** The wiki source does, so
naming is not unprecedented in the corpus, but a script that says `Megan` rather
than `Woman` is following the wiki's descriptive style rather than xkcd's
published text. The section above explains the choice in full.

**The punchline is never explained.** The script stops after the joke. There is
no narration line telling the reader what to conclude.

**The scene description is never elaborate.** `[[A boy sits in a barrel which
is floating in an ocean.]]` is the register. It sets the frame in one sentence
and gets out of the way. It is not stage direction for an animator.

**Visual style is never mentioned in the text.** Stick figures are assumed.

**Dialogue is not exclamation-heavy.** The characters are usually flat and
mild. The humour comes from the situation and the last line, not from volume.

## Writing checklist

Before shipping a script, confirm all six:

1. The alt text is a second beat, not a summary.
2. Speakers are role labels (`Man`, `Woman`, `Person 1`), matching xkcd's own
   transcripts.
3. Panel count is between 1 and 4.
4. Every `[[...]]` stands alone on its own line.
5. The scene description is one spare sentence.
6. The script ends at the joke.
