---
name: xkcd-write
description: Write a new xkcd-style comic script on any topic. Use when asked to "write an xkcd comic about X", "make a comic in the style of xkcd", "xkcd about Y", "write an xkcd script", or to produce a stick-figure comic script with a title and alt text. Produces title, alt text, and a panel script, not an image.
---

# Writing an xkcd comic

## What you produce

Exactly this format, and nothing else:

```
Title: <title>
Alt: <alt text>

[[scene description for panel 1]]
Man: <line>
[[scene description for panel 2]]
Woman: <line>
```

- `Title:` one line. Follow the title-length distribution in the style guide.
- `Alt:` one line. This is a **second joke**, never a summary of the comic. It
  is the single most characteristic piece of xkcd writing, and the easiest to
  get wrong.
- A blank line, then the panel script.
- `[[...]]` holds a scene description. It must stand alone on its line.
- `Speaker: line` holds dialogue. A line may continue over several physical
  lines.

## How to do it

Everything below runs from the xkcd project directory, `/Users/izaakyusop/Code/xkcd`.

1. Read `references/style-guide.md` in full. It sits next to this file.
2. Run the retrieval command for the topic and read the evidence:

```bash
cd /Users/izaakyusop/Code/xkcd && python3 xkcd.py pack "<topic>" --n 8
```

3. Read the exemplars. Notice what they do, not just what they say.
4. Draft. Then check the draft against every rule below before showing it.

If the pack reports no matches, say so, and write from the style guide alone.
Still produce the comic.

## Hard rules

- **Alt text is a second joke.** If the alt text would work as a summary of the
  panels, it is wrong. Rewrite it.
- **No invented names.** The corpus uses role labels: `Man`, `Woman`,
  `Person 1`, `Narrator`, `Figure`, `Girl`. Proper names do exist in the corpus
  but are rare (2 transcripts for `Cueball`, 1 for `Megan`), so do not
  introduce an `Alice` or a `Bob`.
- **One to four panels.** One to four scene blocks covers 74% of the corpus and
  a single block alone is 40%. Long scripts are not xkcd.
- **Never explain the punchline.** State the premise, land the joke, stop. No
  narrator line that tells the reader what to think.
- **The scene description is spare.** `[[A boy sits in a barrel which is
  floating in an ocean.]]` is the register. Not a paragraph of staging.
- **Do not describe visual style in the script.** Stick figures are a given.
- **No em dashes.** Read the exemplars for voice.

## Self-check before showing the draft

Confirm each of these, and say which ones you checked:

- The alt text is a joke, not a summary.
- No speaker is a proper name.
- The panel count is between 1 and 4.
- Every `[[...]]` stands alone on its own line.
- The joke is not explained after the punchline.
- The topic actually appears, rather than being mentioned once and abandoned.

## A worked example

One shape you can aim for:

```
Title: Sourdough

Alt: Day 4. It has developed opinions.

[[A jar on a kitchen counter, with a dark line at the level the starter reached overnight.]]
Person 1: It doubled!
Person 2: It's supposed to do that.
Person 1: I know. I just didn't think it would.
```

Run the pack command before assuming a topic is untouched. The corpus does
contain a sourdough comic: `#2296` (Sourdough Starter), whose alt is `Once the
lockdown is over, let's all get together and swap starters!` A topic being
covered does not close it, since a different joke on the same subject is still
a new comic, but you should know what is already there.
