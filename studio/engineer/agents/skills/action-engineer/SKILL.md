---
name: action-engineer
description: Build, test and submit a new plug-in action for the Puddle Park puppet engine (Blender). Use for every build request.
whenToUse: You are asked to build a request (proposal) for a new action, or to fix one.
---

# Building a plug-in action

## Procedure (follow it in order)
1. `channel proposals` and read the request you were given. Decide the smallest action that does what it asks.
2. `mkdir -p ~/work/<request id>` and write `action.py` there (see the API and the example below).
3. Write `test_scene.json` next to it: 4-6 seconds, the puppets the action needs, the action at t=1.0, and a `say` line
   so the scene is natural. Use `{"t": 0, "do": "shot", "shot": "close:<who>"}` (or "medium") so the action is big
   enough to judge in the pictures; the wide shot makes puppets small. If the action uses a prop, `spawn` it first (at t=0.2, on the table).
4. `eng-test ~/work/<id>/action.py ~/work/<id>/test_scene.json` and read what it prints.
5. Look at `review.jpg` with your image tool (6 frames, the time is printed on each). Check: does it clearly show what
   the request asked, is nothing floating, broken, missing or inside another object, do the puppets still look right
   before and after? A viewer must understand the action without sound.
6. Fix and repeat steps 4-5. At most 6 tries.
7. When it looks right: write `notes.md` (2-4 lines: what the action does, how the producer should use it) and run
   `channel submit <id> ~/work/<id>/action.py`. If it never looked right, do not submit: explain what is wrong instead.

## Plug-in file
Four constants and a `run(api, ev)` function, nothing else at the top level (no imports needed: everything is on `api`).
```python
ACTION = "new_name"            # lowercase_with_underscores, not a built-in (shot say hop move wave point look spawn bounce eat numeral)
DESCRIPTION = "who ... (about N s)"   # one line for the producer: what it looks like and how long it takes
NEEDS = ["who"]                # required event fields: who, name, at, to, text (only the ones you use)
PARAMS = "new_name {who}"      # one-line usage

def run(api, ev):              # ev is the event dict: ev["t"] (seconds) plus the fields you named
    ...
```

## The API
- `api.puppet(name)` a Puppet. Its parts, all animatable with `api.key`:
  - `root` (at the floor; move it to move the puppet), `body` (scale it to squash/stretch; `body_base_scale` is its rest scale)
  - `mouth` (`mouth_closed` is its rest scale; scale z up to open it), `pupils` (list of (pupil, home location))
  - `arms` (list of (side, pivot); rotate the pivot: `(0, -side * 2.3, 0)` raises that arm, `(0, 0, 0)` is down)
  - `size`, `kind` ("small" pip, "tall" bramble, "bird" wren, "puppy" biscuit), `head_world()`, `mouth_world()` (Vectors)
- `api.prop(name)` a spawned prop object (apple, ball, star); `api.spawned` all of them by name; `api.cast` all puppets
- `api.key(obj, "location"|"rotation_euler"|"scale", frame, value)` sets the value and keyframes it
- `api.F(seconds)` the frame number for a time. Animation shows 8 poses a second, so keep every pose at least 0.12 s.
- Built-in moves to reuse: `api.hop(p, t, height=0.6)`, `api.move(p, t, to=[x, y], dur=1.0)`, `api.wave(p, t, dur=1.5)`,
  `api.point(p, t, dur=1.2)`, `api.look(p, t, at=[x, y, z])`, `api.eat(p, t, prop_obj)`
- Making things: `api.sphere(name, (x,y,z), (rx,ry,rz), material, parent=None)`, `api.cylinder(name, (x,y,z), r, depth, material)`,
  `api.box(name, (x,y,z), (sx,sy,sz), material)`, `api.felt("red"|"orange"|"yellow"|"green"|"blue"|"purple"|"pink"|"brown"|"white"|"black")`,
  `api.glossy(color)`, `api.attach(child, parent)`, `api.new_prop("apple"|"ball"|"star", name, (x,y,z))`
- `api.pop_in(obj, t)` grows an object in, `api.pop_out(obj, t)` shrinks it away. `api.Vector`, `api.math` are there too.
- Stage: floor z=0; table top z=1.12, x from -0.5 to 1.7; puppets stand between x=-3 and 3.5, y about 0.
  The camera looks from -y toward +y: "in front of" a puppet means smaller y.

## Rules
- Keep it short: 0.5-3 seconds. Return each part to its rest pose at the end (arms down, body at body_base_scale).
- Objects you create must be named uniquely: include the puppet name and ev["t"], e.g. f"{p.name}_hat_{ev['t']}".
- No loops that depend on anything but small fixed numbers. No file, network or system access: the render user has none.
- Things the engine cannot do and you should not fake: sound, music, new characters, camera moves.

## Common mistakes
- Full turns: key the rotation up to `2 * api.math.pi` and leave it there. Never key it back to 0 afterwards: that
  plays as a fast spin backwards. (A turn of 2*pi looks the same as 0.)
- Running eng-test in the background and then guessing: always wait for eng-test to finish and read its output.
- Moving `root` sideways and not back: the puppet ends up somewhere else for the rest of the scene.

## Example (a working action)
See /hyperai/home/engineer/examples/jump_for_joy.py:
```python
ACTION = "jump_for_joy"
DESCRIPTION = "who jumps twice for joy with both arms up (about 1.4 s)"
NEEDS = ["who"]
PARAMS = "jump_for_joy {who}"

def run(api, ev):
    p = api.puppet(ev["who"])
    t = float(ev["t"])
    api.hop(p, t, height=0.5)
    api.hop(p, t + 0.7, height=0.5)
    for side, pivot in p.arms:
        up = (0, -side * 2.3, 0)
        api.key(pivot, "rotation_euler", api.F(t), (0, 0, 0))
        api.key(pivot, "rotation_euler", api.F(t + 0.2), up)
        api.key(pivot, "rotation_euler", api.F(t + 1.2), up)
        api.key(pivot, "rotation_euler", api.F(t + 1.4), (0, 0, 0))
```
Its test scene:
```json
{"seconds": 4, "cast": ["pip", "biscuit"],
 "timeline": [{"t": 0, "do": "shot", "shot": "wide"},
              {"t": 0.3, "do": "say", "who": "pip", "text": "We did it!"},
              {"t": 1.0, "do": "jump_for_joy", "who": "pip"}]}
```
