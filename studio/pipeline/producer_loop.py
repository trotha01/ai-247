#!/usr/bin/env python3
"""Producer loop: the local Qwen writes the channel, one 15 s scene at a time, forever.

  python producer_loop.py --root /hyperai/home/loop/puddle --url http://127.0.0.1:8080

Talking to the producer while it runs (no restart needed):
  * drop a text file into ROOT/producer/directions/ ("more songs", "Biscuit learns the letter B all next hour",
    "stop doing counting for now"). The next round reads it, adds it to the standing notes
    (ROOT/producer/notes.md, newest last) and moves the file to directions/read/.
  * edit ROOT/producer/notes.md or brief.md directly: both are re-read every round.
  * touch ROOT/STOP to stop both the producer and the channel worker.

The producer keeps the worker's inbox TARGET scenes deep, writes PARALLEL scenes at once, remembers what aired
(ROOT/producer/history.jsonl) so it does not repeat itself, and repairs or rejects scripts the Blender engine
cannot play. Each scene's characters come from the fixed cast below, so they look and sound the same every time.
"""
import argparse
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Fixed cast: looks + voices. The producer only chooses who appears; positions are assigned by headcount.
CAST = {
    "pip": {"kind": "small", "color": "orange", "size": 0.9, "voice": {"id": "af_sky", "speed": 1.05, "pitch": 1.3},
            "about": "small squat orange fuzzy puppet with a little sprout on his head, cheerful and curious, squeaky voice"},
    "bramble": {"kind": "tall", "color": "green", "size": 1.05, "voice": {"id": "am_michael", "speed": 0.9, "pitch": 0.85},
                "about": "tall shaggy green puppet with long floppy ears and a round nose, slow gentle deep voice, patient teacher"},
    "wren": {"kind": "bird", "color": "purple", "size": 0.95, "voice": {"id": "af_bella", "speed": 1.05, "pitch": 1.15},
             "about": "purple felt bird with wings, a yellow beak and tail feathers, sing-song voice, loves songs and rhymes"},
    "biscuit": {"kind": "puppy", "color": "yellow", "size": 0.95, "voice": {"id": "am_puck", "speed": 1.1, "pitch": 1.2},
                "about": "yellow puppy with floppy brown ears, a snout and a wagging tail, playful and giggly, loves snacks"},
}
SPOTS = {1: [(-1.2, 0.2)], 2: [(-1.7, 0.2), (3.0, 0.3)], 3: [(-2.9, 0.3), (-1.3, 0.1), (3.0, 0.3)]}
SCENE_DEFAULTS = {"seconds": 15, "fps": 24, "step": 3, "resolution": [1280, 720], "samples": 8, "on_twos": False,
                  "frame_format": "JPEG",
                  "look": {"sheen": 0.15, "view": "Standard", "exposure": -0.2, "world": 0.35, "key": 350}}
PROPS = ("apple", "ball", "star")

ENGINE_RULES = """Each scene is 15 seconds of a felt-puppet stage: a table in the middle (table top z=1.12, x from -0.5 to 1.7),
puppets standing around it. You write it as a JSON scene script. Timeline actions (every event has "t" in seconds 0-14.5 and "do"):
shot {shot: "wide"|"medium"|"close:<who>", smooth?: seconds}   (first event must be a shot at t=0)
say {who, text}                 (one short sentence, max 12 words; the voice engine times it, about 0.4 s per word)
hop {who}   wave {who, dur}   point {who, dur}   look {who, at:[x,y,z]}   move {who, to:[x,y], dur}
spawn {prop: "apple"|"ball"|"star", name, at:[x,y,z]}   (put props on the table top: z=1.12, x -0.5..1.7, y about 0)
bounce {name}                   (a prop that was spawned earlier)
eat {who, name}                 (who eats a spawned prop: it flies to their mouth, three chomps, and it is gone. Whenever
                                a character says they eat or taste something, show it with eat. Gone means gone: do not
                                bounce or eat it again afterwards)
numeral {text, at:[x,y,z], dur, color?}   (a big floating number or letter, 1-3 characters, e.g. at [0.6,0,2.4])
IMAGES (painted by an image model, made once and reused):
"backdrop": the name of a READY backdrop from the list below, or "puddle_park" for the home set (rainbow, felt houses, pond).
"card": optional, the name of a READY title card, shown full screen for 2 seconds before the scene. Use cards at the start
of a new segment (opener, song, a new lesson topic), not on every scene.
"order_images": optional, ask for new images you want later: {name (short_snake_case), kind: "backdrop"|"card", prompt: what
it shows, text: the exact words on a card (1-3 short words)}. Ordered images take several minutes and appear in the READY lists
when done; never use an image in the same scene you order it. Order only what you will reuse, at most 1-2 at a time.
Leave about 0.5 s between one character's lines and the next. Use 8 to 30 events. Characters should react:
look at whoever is talking, hop when excited, wave hello and goodbye. Use close shots on the speaker for important lines."""

EVENT = {"type": "object", "properties": {
    "t": {"type": "number"}, "do": {"type": "string", "enum": ["shot", "say", "hop", "move", "wave", "point", "look",
                                                               "spawn", "bounce", "eat", "numeral"]},
    "who": {"type": "string"}, "text": {"type": "string"}, "dur": {"type": "number"}, "shot": {"type": "string"},
    "smooth": {"type": "number"}, "prop": {"type": "string"}, "name": {"type": "string"},
    "at": {"type": "array", "items": {"type": "number"}}, "to": {"type": "array", "items": {"type": "number"}},
    "color": {"type": "string"}}, "required": ["t", "do"]}
SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"},
    "segment": {"type": "string", "enum": ["opener", "lesson", "song", "story", "game", "movement break", "closer"]},
    "cast": {"type": "array", "items": {"type": "string", "enum": list(CAST)}, "minItems": 1, "maxItems": 3},
    "backdrop": {"type": "string"}, "card": {"type": "string"},
    "order_images": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "kind": {"type": "string", "enum": ["backdrop", "card"]},
        "prompt": {"type": "string"}, "text": {"type": "string"}}, "required": ["name", "kind", "prompt"]}},
    "timeline": {"type": "array", "items": EVENT, "minItems": 8, "maxItems": 30}},
    "required": ["title", "segment", "cast", "backdrop", "timeline"]}
MAX_ORDERS = 6  # image orders waiting for MOSS at once
ACTIONS_LIVE = Path("/hyperai/home/loop/puddle/actions/live")
BUILTIN = {"shot", "say", "hop", "move", "wave", "point", "look", "spawn", "bounce", "eat", "numeral"}


def live_actions() -> dict:
    """Approved plug-in actions: {name: {"DESCRIPTION", "NEEDS", "PARAMS"}}, read as text with ast (never imported here)."""
    import ast
    out = {}
    for f in sorted(ACTIONS_LIVE.glob("*.py")) if ACTIONS_LIVE.exists() else []:
        try:
            meta = {}
            for node in ast.parse(f.read_text()).body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                        and node.targets[0].id in ("ACTION", "DESCRIPTION", "NEEDS", "PARAMS"):
                    meta[node.targets[0].id] = ast.literal_eval(node.value)
            if meta.get("ACTION") and meta["ACTION"] not in BUILTIN:
                out[meta["ACTION"]] = meta
        except Exception:
            continue
    return out


def schema_with(extra_actions) -> dict:
    s = json.loads(json.dumps(SCHEMA))
    s["properties"]["timeline"]["items"]["properties"]["do"]["enum"] += sorted(extra_actions)
    return s


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "scene"


def repair(raw, ready_backdrops=(), ready_cards=(), plugins=None):
    """Make a model-written scene safe for puddle.py; returns (scene, notes) or raises ValueError."""
    who = [w for w in dict.fromkeys(raw.get("cast", [])) if w in CAST][:3]
    if not who:
        raise ValueError("no known cast")
    cast = {}
    for w, at in zip(who, SPOTS[len(who)]):
        c = {k: v for k, v in CAST[w].items() if k != "about"}
        cast[w] = {**c, "at": list(at)}
    plugins = plugins or {}
    notes, events, spawned, pnum = [], [], set(), 0
    for e in sorted(raw.get("timeline", []), key=lambda e: float(e.get("t", 0))):
        e = dict(e)
        e["t"] = round(min(max(float(e.get("t", 0)), 0.0), 14.5), 2)
        do = e.get("do")
        if e.get("who") is not None and e["who"] not in cast:
            notes.append(f"dropped {do} by unknown {e['who']}")
            continue
        if (do in ("say", "hop", "wave", "point", "look", "move", "eat")
                or "who" in (plugins.get(do) or {}).get("NEEDS", [])) and "who" not in e:
            notes.append(f"dropped {do} without who")
            continue
        if do == "say":
            if not str(e.get("text", "")).strip():
                continue
            e["dur"] = float(e.get("dur") or 2.0)
        elif do in ("wave", "point"):
            e["dur"] = min(max(float(e.get("dur") or 1.2), 0.4), 3.0)
        elif do == "move":
            if len(e.get("to", [])) != 2:
                continue
            e["to"] = [min(max(float(e["to"][0]), -3.0), 3.5), min(max(float(e["to"][1]), -0.5), 1.5)]
            e["dur"] = min(max(float(e.get("dur") or 1.0), 0.3), 3.0)
        elif do == "look":
            if len(e.get("at", [])) != 3:
                continue
        elif do == "shot":
            s = str(e.get("shot", "wide"))
            if s.startswith("close:") and s[6:] not in cast:
                s = "medium"
            elif not s.startswith("close:") and s not in ("wide", "medium"):
                s = "wide"
            e["shot"] = s
        elif do == "spawn":
            if e.get("prop") not in PROPS:
                e["prop"] = "apple"
            name = e.get("name") or f"{e['prop']}{pnum}"
            while name in spawned:
                name += "x"
            pnum += 1
            e["name"] = name
            at = (list(e.get("at", [])) + [0.6, 0.0, 1.12])[:3]
            e["at"] = [min(max(float(at[0]), -0.5), 1.7), min(max(float(at[1]), -0.4), 0.4), 1.12 + 0.18]
            spawned.add(name)
        elif do == "bounce":
            if e.get("name") not in spawned:
                notes.append(f"dropped bounce of unspawned {e.get('name')}")
                continue
        elif do == "eat":
            if e.get("name") not in spawned:
                notes.append(f"dropped eat of unspawned or eaten {e.get('name')}")
                continue
            spawned.discard(e["name"])
        elif do == "numeral":
            e["text"] = str(e.get("text", ""))[:3]
            if not e["text"].strip() or len(e.get("at", [])) != 3:
                continue
            e["dur"] = float(e.get("dur") or 3.0)
        elif do in plugins:
            needs = plugins[do].get("NEEDS", [])
            if "name" in needs and e.get("name") not in spawned:
                notes.append(f"dropped {do} on unspawned {e.get('name')}")
                continue
            if any(k not in e for k in needs) or ("at" in needs and len(e.get("at", [])) != 3) \
                    or ("to" in needs and len(e.get("to", [])) != 2):
                notes.append(f"dropped {do} missing {needs}")
                continue
        else:
            continue
        events.append({k: v for k, v in e.items() if v is not None})
    if not events or events[0]["do"] != "shot" or events[0]["t"] > 0:
        events.insert(0, {"t": 0.0, "do": "shot", "shot": "wide"})
    if sum(1 for e in events if e["do"] == "say") < 2:
        raise ValueError("fewer than 2 lines of dialogue")
    scene = {**SCENE_DEFAULTS, "title": str(raw.get("title", "untitled"))[:80], "segment": raw.get("segment", "lesson"),
             "cast": cast, "timeline": events}
    bd, cd = raw.get("backdrop"), raw.get("card")
    if bd and bd in ready_backdrops:
        scene["backdrop"] = bd
    elif bd and bd != "puddle_park":
        notes.append(f"backdrop {bd} not ready: home set")
    if cd and cd in ready_cards:
        scene["card"] = cd
    elif cd:
        notes.append(f"card {cd} not ready: none")
    return scene, notes


class Producer:
    def __init__(self, a):
        self.a = a
        self.pdir = a.root / "producer"
        self.inbox = a.root / "inbox"
        self.dirs = self.pdir / "directions"
        for d in (self.inbox, self.dirs / "read"):
            d.mkdir(parents=True, exist_ok=True)
        self.notes = self.pdir / "notes.md"
        self.notes.touch()
        self.hist = self.pdir / "history.jsonl"
        self.hist.touch()
        self.seq = int(time.time())
        import backdrops
        self.lib = backdrops.Library(a.root / "library")

    def take_directions(self):
        for f in sorted(self.dirs.glob("*")):
            if not f.is_file():
                continue
            text = f.read_text().strip()
            if text:
                with self.notes.open("a") as n:
                    n.write(f"- ({time.strftime('%Y-%m-%d %H:%M')}) {text}\n")
                log(f"NEW DIRECTION: {text[:200]}")
            f.rename(self.dirs / "read" / f"{time.strftime('%Y%m%dT%H%M%S')}-{f.name}")

    def recent(self, n=16):
        lines = self.hist.read_text().splitlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]

    def system(self):
        brief = (self.pdir / "brief.md").read_text() if (self.pdir / "brief.md").exists() else ""
        cast = "\n".join(f"- {k}: {v['about']}" for k, v in CAST.items())
        notes = self.notes.read_text().strip()
        s = (f"You are the producer of an always-on TV channel. You decide what airs next and write it.\n\n"
             f"CHANNEL BRIEF:\n{brief}\n\nCAST YOU CAN USE (names exactly as written):\n{cast}\n\n{ENGINE_RULES}")
        bds = self.lib.ready("backdrop")
        cds = self.lib.ready("card")
        s += "\n\nREADY BACKDROPS:\n- puddle_park: the home set (rainbow, felt houses, pond)\n" + "\n".join(
            f"- {k}: {v['prompt']}" for k, v in bds.items())
        s += "\n\nREADY TITLE CARDS:\n" + ("\n".join(f"- {k}: says \"{v.get('text')}\"" for k, v in cds.items()) or "- none yet")
        pend = self.lib.pending()
        if pend:
            s += "\n\nALREADY ORDERED, NOT READY YET (do not order again): " + ", ".join(r["name"] for r in pend)
        if len(pend) >= MAX_ORDERS:
            s += "\nThe image queue is full: do not order images now."
        plug = live_actions()
        if plug:
            s += "\n\nEXTRA ACTIONS (new, use them where they fit):\n" + "\n".join(
                f"{m.get('PARAMS', k)}   ({m.get('DESCRIPTION', '')})" for k, m in plug.items())
        if notes:
            s += ("\n\nDIRECTIONS FROM THE CHANNEL OWNERS (follow them; newer ones win when they conflict):\n" + notes)
        return s

    def user_msg(self, slot):
        rec = self.recent()
        aired = "\n".join(f"- [{r['segment']}] {r['title']} ({', '.join(r['cast'])})" for r in rec) or "- nothing yet: start with an opener"
        return (f"What aired most recently (oldest first):\n{aired}\n\n"
                f"Write the next scene{' after that one' if slot else ''}. It must follow on naturally, not repeat a recent "
                f"title or topic, and vary the segment type. Scene {slot + 1} of this batch.")

    def write_one(self, slot):
        body = {"messages": [{"role": "system", "content": self.system()},
                             {"role": "user", "content": self.user_msg(slot)}],
                "temperature": 0.85, "max_tokens": 2500, "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {"name": "scene", "schema": schema_with(live_actions())}}}
        req = urllib.request.Request(f"{self.a.url}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t = time.time()
        r = json.load(urllib.request.urlopen(req, timeout=600))
        raw = json.loads(r["choices"][0]["message"]["content"])
        scene, notes = repair(raw, self.lib.ready("backdrop"), self.lib.ready("card"), live_actions())
        for o in raw.get("order_images") or []:
            if len(self.lib.pending()) >= MAX_ORDERS:
                break
            name = self.lib.request(o.get("name"), o.get("kind"), o.get("prompt", ""), text=o.get("text"))
            if name:
                notes.append(f"ordered {o.get('kind')} {name}")
        return scene, notes, time.time() - t

    def queued(self):
        return len(list(self.inbox.glob("*.json")))

    def run(self):
        log(f"producer: {self.a.url}, inbox {self.inbox} (keep {self.a.target} queued, {self.a.parallel} at once)")
        while not (self.a.root / "STOP").exists():
            self.take_directions()
            need = self.a.target - self.queued()
            if need <= 0:
                time.sleep(5)
                continue
            n = min(need, self.a.parallel)
            with ThreadPoolExecutor(n) as ex:
                results = list(ex.map(lambda i: self._safe(i), range(n)))
            for res in results:
                if not res:
                    continue
                scene, notes, dt = res
                self.seq += 1
                name = f"{self.seq}-{slug(scene['title'])}.json"
                tmp = self.inbox / (name + ".tmp")
                tmp.write_text(json.dumps(scene, indent=1))
                tmp.rename(self.inbox / name)  # atomic: the worker never sees half a file
                with self.hist.open("a") as h:
                    h.write(json.dumps({"t": time.time(), "file": name, "title": scene["title"], "segment": scene["segment"],
                                        "cast": list(scene["cast"])}) + "\n")
                log(f"WROTE [{scene['segment']}] {scene['title']} ({len(scene['timeline'])} events, {dt:.0f}s, "
                    f"backdrop {scene.get('backdrop', 'puddle_park')}{', card ' + scene['card'] if scene.get('card') else ''})"
                    + (f" repairs: {notes[:3]}" if notes else ""))
        log("stopped")

    def _safe(self, i):
        try:
            return self.write_one(i)
        except Exception as e:
            log(f"scene rejected: {e!r}"[:300])
            return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("/hyperai/home/loop/puddle"))
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--target", type=int, default=8, help="scenes to keep queued for the worker")
    ap.add_argument("--parallel", type=int, default=2, help="scenes written at once")
    Producer(ap.parse_args()).run()


if __name__ == "__main__":
    main()
