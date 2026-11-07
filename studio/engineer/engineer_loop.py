#!/usr/bin/env python3
"""Engineer loop (runs as root, starts the agent as the unprivileged user "eng").

Picks the oldest request with status "new" from ROOT/proposals, marks it "building", and runs the engineer agent
(dsh headless, Qwen, with the action-engineer skill) on it in ~eng/work/<id>. The agent tests its plug-in off air with
eng-test and hands it in with `channel submit` (status becomes "ready"; an owner approves it with `channel approve`).
If the agent ends without submitting, the request becomes "failed" with the agent's own explanation.

  python engineer_loop.py            # forever, one request at a time
"""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path("/hyperai/home/loop/puddle")
PROPOSALS = ROOT / "proposals"
ENG_HOME = Path("/output/eng")
TIME_LIMIT_S = 2700  # whole request
ATTEMPT_S = 900      # one run of the agent


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load(d):
    return json.loads((d / "request.json").read_text())


def save(d, req, event):
    req.setdefault("history", []).append(f"{time.strftime('%Y-%m-%d %H:%M')} {event}")
    tmp = d / "request.tmp"
    tmp.write_text(json.dumps(req, indent=1))
    tmp.rename(d / "request.json")


def run_agent(d, name, prompt):
    """One fresh, short dsh conversation as the user eng. Returns its final text."""
    env_vars = (f"HOME={ENG_HOME} DSH_HOME={ENG_HOME}/.dsh DSH_AGENTS_HOME=/hyperai/home/engineer/agents LLAMA_API_KEY=none "
                f"PATH=/hyperai/home/node/bin:/hyperai/home/dsh-global/bin:/hyperai/home/bin:/usr/local/bin:/usr/bin:/bin")
    f = d / f"{name}.txt"
    f.write_text(prompt)
    os.chmod(f, 0o644)
    try:
        r = subprocess.run(["su", "eng", "-c", f"cd {ENG_HOME}/work && {env_vars} dsh --profile headless --json - < {f}"],
                           capture_output=True, text=True, timeout=ATTEMPT_S)
        out, err = r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = f"(stopped after {ATTEMPT_S // 60} minutes)"
    final = ""
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") in ("final", "text") and ev.get("text"):
            final = ev["text"]
    with open(d / "engineer.log", "a") as lg:
        lg.write(f"\n===== {name}\n{out[-30000:]}\n{err[-3000:]}\n")
    return final.strip()


def build(d, req):
    """Builder and reviewer take turns, each in a fresh short conversation (a long one runs out of model memory):
    the builder writes and test-renders the action, the reviewer looks at the pictures and either submits it or writes
    review.md with what to fix for the next builder round."""
    pid = req["id"]
    req["status"] = "building"
    save(d, req, "building")
    work = ENG_HOME / "work" / pid
    t0 = time.time()
    ask = f'Request {pid}: "{req["title"]}". What it should do: {req["what"]}'
    for rnd in range(1, 4):
        feedback = (work / "review.md").read_text().strip() if (work / "review.md").exists() else ""
        build_prompt = (f"You are the BUILDER. {ask}\n\nYour folder: ~/work/{pid} (it may already hold an earlier action.py "
                        f"and test_scene.json: start from them). "
                        + (f"The reviewer asked for these fixes:\n{feedback}\n\n" if feedback else "")
                        + "Using the action-engineer skill, write or fix action.py and test_scene.json, then run "
                        f"`eng-test ~/work/{pid}/action.py ~/work/{pid}/test_scene.json` and wait for it to finish. "
                        "If it prints problems, fix and run it again. Stop as soon as eng-test finishes with no problems. "
                        "Do not judge the pictures and do not submit: the reviewer does that. End with one sentence.")
        if (work / "review.md").exists():
            (work / "review.md").rename(work / f"review.round{rnd - 1}.md")
        log(f"{pid}: round {rnd} builder")
        run_agent(d, f"round{rnd}_builder", build_prompt)
        if not (work / "review.jpg").exists() or not (work / "action.py").exists():
            continue
        review_prompt = (f"You are the REVIEWER. {ask}\n\nIn ~/work/{pid} the builder made action.py and test pictures. "
                         f"Look at ~/work/{pid}/review_small.jpg with your image tool (6 frames in order, times printed) "
                         f"and read action.py. Decide: does it clearly show what the request asks, with nothing broken, "
                         f"floating, missing or inside something else, and the puppet back to normal at the end?\n"
                         f"- If YES: write ~/work/{pid}/notes.md (2-3 lines: what it does, when the show should use it), then run "
                         f"`channel submit {pid} ~/work/{pid}/action.py`.\n"
                         f"- If NO: write ~/work/{pid}/review.md with at most 3 short bullet points of what to fix. Do not edit "
                         f"action.py yourself.\nEnd with one sentence.")
        log(f"{pid}: round {rnd} reviewer")
        answer = run_agent(d, f"round{rnd}_reviewer", review_prompt)
        if load(d)["status"] != "building" or time.time() - t0 > TIME_LIMIT_S:
            break
    req = load(d)
    if req["status"] == "building":
        last = (work / "review.md").read_text() if (work / "review.md").exists() else ""
        req.update(status="failed", reason=(last or "the engineer could not finish it")[-400:])
        save(d, req, "engineer ended without submitting")
    log(f"{pid}: {req['status']} after {time.time() - t0:.0f}s")


def main():
    log("engineer loop: watching", PROPOSALS)
    while not (ROOT / "STOP").exists():
        todo = sorted(p.parent for p in PROPOSALS.glob("*/request.json") if load(p.parent)["status"] == "new") \
            if PROPOSALS.exists() else []
        if not todo:
            time.sleep(20)
            continue
        d = todo[0]
        req = load(d)
        log(f"building {req['id']}: {req['title']}")
        try:
            build(d, req)
        except Exception as e:
            log(f"engineer loop error on {req['id']}: {e!r}")
            req = load(d)
            req.update(status="failed", reason=f"engineer loop error: {e!r}"[:400])
            save(d, req, "error")
    log("stopped")


if __name__ == "__main__":
    main()
