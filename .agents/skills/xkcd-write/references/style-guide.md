# xkcd style guide

Derived from the 3301-comic corpus in `data/xkcd.db`. Every number here is
measured, and the command that produced it is named so you can re-check it.

Regenerate the raw figures with `python3 xkcd.py stats --top 25`.

## Read this first: what the corpus can and cannot tell you

The corpus covers 3301 comics, dated 2006-01-01 to 2026-09-23.

**1665 of them have a transcript. 1636 do not.** Transcripts stop at `#1677`,
with a few gaps before that. Everything structural below (panel counts,
speakers, dialogue) is therefore a statement about the first half of xkcd's
history, not about the comic as a whole.

Title and alt text exist for 3298 of 3301 comics, and that is the writing that
spans the entire run. When you are unsure, trust the title-and-alt evidence.

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

Panel counts come from line-standing `[[...]]` scene blocks across the 1665
transcripts. Note that this counts scene descriptions, not panels; the maximum
of 86 is a count of descriptions in one long transcript, so treat this as a
shape indicator rather than a precise panel count.

| Scene blocks | Comics |
| --- | --- |
| 0 | 207 |
| 1 | 673 |
| 2 | 176 |
| 3 | 194 |
| 4 | 196 |
| 5 or more | 219 |

**One to four blocks covers 74% of the corpus.** One block alone is 40%. The
most common xkcd shape by a wide margin is a single scene-setting description
followed by dialogue, with the punchline arriving in the last line of speech.

Zero blocks is not a failure. 207 transcripts have no line-standing scene block
at all, because the scene description is inline in a dialogue line rather than
standing on its own.

## Speakers

The corpus does not name its characters. Across 1665 transcripts, the most
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

Two things follow from this.

**Role labels are the convention.** `Man`, `Woman`, `Person 1`, `Person 2`,
`Narrator`, `Figure`. Use these.

**Proper names exist but are rare, and are not worth copying.** Across 1665
transcripts, `Cueball` appears as a speaker in 2 comics (`#1324`, `#1486`),
`Megan` in 1 (`#478`), and `Black Hat` in 4 (`#146`, `#1136`, `#1137`,
`#1321`). `Megan` turns up far more often inside dialogue than as a speaker
label. Inventing a name like `Alice` or `Bob` has no precedent here, so do not.

An earlier draft of this guide claimed `Cueball` and `Megan` never appear. That
was wrong, and it came from sampling comics rather than searching all of them.
The figures above are from querying every transcript.

**The recurring visual cast is described, not named.** The hat character appears
as `Hat Guy` (19), `Hat guy` (10), `Black hat guy` (12), and `Black Hat` (4),
which is 45 occurrences in total. `Beret guy` appears 11 times. These describe
the drawing rather than name a person.

`Person 1` and `Person 2` are positional labels for interchangeable speakers.
`Caption` is a legitimate speaker, because a caption drawn inside a panel is
part of the comic.

## Topics

Counts are recall figures: a comic counts toward a topic if any of the topic's
synonyms appears anywhere in its title, alt text, or transcript, so these
overcount. They indicate which subjects have depth, not exact totals.

```
381  computers      103  parenting      49  cats
314  work           101  politics       46  time-travel
254  meta            96  social-media   44  weather
252  space           92  maps           42  chemistry
177  internet        89  existential    40  gardening
148  physics         88  sex            27  economics
144  statistics      80  history        20  climate
131  romance         78  engineering    14  philosophy
127  health          76  programming
119  food            72  linguistics
113  math            71  biology
                     55  ai
```

Subjects with real depth: computing and the internet, work and office life,
space and physics, mathematics and statistics, romance and relationships, and
the self-referential `meta` bucket.

Subjects with almost no depth: philosophy (14), climate (20), economics (27),
gardening (40). A comic about gardening is nearly unexplored ground.

The `meta` bucket at 254 is worth noting. xkcd writes about being a webcomic,
about its own panels and alt text, often enough that self-reference is a
first-class subject rather than a novelty.

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

**The alt text never summarises the panels.** Not once in 3298 comics is the
alt a description of what happened. If your alt would work as a caption, it is
the wrong alt.

**Speakers are never proper names.** See above.

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
2. No speaker is a proper name.
3. Panel count is between 1 and 4.
4. Every `[[...]]` stands alone on its own line.
5. The scene description is one spare sentence.
6. The script ends at the joke.
