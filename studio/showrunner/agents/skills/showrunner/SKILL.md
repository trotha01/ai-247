---
name: showrunner
description: Watch and steer the Puddle Park channel (status, what is on air, scripts, directions, brief, backdrops and title cards). Use for anything about the channel, the show, the producer, scenes, puppets or images.
whenToUse: The user asks how the channel is doing, wants to see or change the show, give the producer a direction, order a backdrop or title card, or check that everything is running.
---

# Showrunner routine

Everything goes through the `channel` command (run it with your shell tool).

| Command | What it does |
|---|---|
| `channel status` | Are the producer, worker and Qwen running; production speed (1.0x = real time); queue; image library; GPU/RAM; stream health |
| `channel frames [N]` | Saves N frames (default 4, ~6 s apart) of what is on air right now and prints their paths. Look at them with your image tool |
| `channel recent [N]` | The last N scenes written: time, segment type, title, cast |
| `channel scene [NAME\|last]` | One scene's full script: backdrop, card, cast, every timed action and line |
| `channel direct "TEXT"` | Adds a standing direction for the producer (read within seconds, kept until removed) |
| `channel notes` / `channel unnote N` | List the standing directions / remove number N |
| `channel brief` | The channel bible the producer works from |
| `channel library` | Ready backdrops and title cards, and images still being made |
| `channel order backdrop NAME "PROMPT"` | Order a panoramic backdrop from MOSS |
| `channel order card NAME "PROMPT" --text "WORDS"` | Order a full-screen title card with exact words (1-3 short words) |
| `channel propose "TITLE" "WHAT"` | Ask the engineer for a new action the engine cannot do yet (see below) |
| `channel proposals` / `channel actions` | Requests and their status / new actions that are approved and usable |
| `channel logs producer\|worker [N]` | Last N log lines |
| `channel restart producer\|worker` | Only when `status` shows one STOPPED or the log shows it stuck for 5+ minutes |

## When someone asks "how is the channel?"
1. `channel status`. Production speed below ~0.9x for long means viewers see replays; say so.
2. `channel frames 4` and look at the images. Describe what is actually on screen.
3. `channel recent 10`. Look for repetition (same character leading every scene, same topic, same backdrop).
4. Answer in a few sentences: what is on, what is good, what you would improve next.

## Giving directions
- One idea per direction, concrete and checkable: "Use Wren as the lead in at least one scene in four", not "be more varied".
- Check `channel notes` first; remove directions that are outdated or contradict the new one (`channel unnote N`).
- After directing, tell the person when to expect the change: queued scenes air first, so about 2-3 minutes.

## What the engine can do (so you only ask for things that can happen)
Scenes are 15 seconds on a felt-puppet stage with a table. Puppets, each with its own shape: pip (small squat orange,
sprout on his head, squeaky), bramble (tall green, long hanging ears, round nose, deep gentle voice), wren (purple bird with
wings, beak, crest and tail, sing-song), biscuit (yellow puppy with floppy brown ears, snout and tail, giggly). Actions: say
a line, hop, wave, point, look at something, move around, spawn a prop (apple, ball, star) on the table, bounce it, EAT it
(it flies to the puppet's mouth, three chomps, gone), show a big floating number or letter, and camera shots (wide,
medium, close-up on one puppet). A scene can use a MOSS backdrop and start with a
2-second title card. `channel actions` lists extra actions the engineer has added since.

## New actions: the engineer
When someone wants a puppet to do something the engine cannot do yet (dance, spin, hug, juggle, wear a hat, blow bubbles),
file it: `channel propose "Biscuit can dance" "A happy little dance for any puppet: sway side to side, arms up, two small
hops, about 2 seconds. Used when characters celebrate or a song plays."` Describe what it should LOOK like, how long it
takes and when the show would use it. The engineer agent builds and tests it off air (10-30 minutes); then an owner
approves it, and only then can the producer use it. Check progress with `channel proposals`. Things that are not
actions (new characters, music, sound effects, longer scenes) still go in ~/work/proposals.md for the owners.

## Images
MOSS makes images between blocks, at most every 10 minutes, about 40 seconds each, so an order takes 5-15 minutes to
appear in `channel library`. Order images the show will reuse (a place, a recurring segment's title card), not one-offs.
Backdrops: describe the place, not characters ("a felt bakery with round bread loaves on wooden shelves").
