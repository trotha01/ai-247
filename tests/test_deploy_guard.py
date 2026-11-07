"""Guard: no workflow deploys or runs anything under studio/ (Puddle Park; its owners deploy it by hand).

studio/cloudflare/*/wrangler.toml name other Workers and buckets on another Cloudflare account. If any workflow
ever ran wrangler there, or listed studio/ in its triggers or steps, our secrets would deploy someone else's
config. These checks read the workflow files as text (no YAML dependency) and ignore comment lines.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


def code_lines(path: Path) -> list[tuple[int, str]]:
    return [(i, l) for i, l in enumerate(path.read_text().splitlines(), 1) if not l.lstrip().startswith("#")]


def test_workflows_exist():
    assert any(p.name == "deploy.yml" for p in WORKFLOWS)


def test_no_workflow_mentions_studio():
    hits = [f"{p.name}:{i}: {l.strip()}" for p in WORKFLOWS for i, l in code_lines(p) if "studio" in l.lower()]
    assert not hits, "workflows must never touch studio/:\n" + "\n".join(hits)


def test_deploy_triggers_are_ours_only():
    text = (ROOT / ".github/workflows/deploy.yml").read_text()
    block = re.search(r"^  push:\n(?:    .*\n)+", text, re.M).group(0)
    paths = re.findall(r'^      - "([^"]+)"', block, re.M)
    assert paths == ["worker/**", "site/**", "scripts/smoke.sh", ".github/workflows/deploy.yml"], paths


def test_deploy_runs_wrangler_only_in_worker_and_site():
    lines = code_lines(ROOT / ".github/workflows/deploy.yml")
    wd = [l.split(":", 1)[1].strip() for _, l in lines if re.match(r"\s*working-?[dD]irectory:", l)]
    assert wd and set(wd) == {"worker"}, wd
    commands = [l.split(":", 1)[1].strip() for _, l in lines if re.match(r"\s*command:", l)]
    assert commands, "no wrangler commands found"
    for c in commands:
        assert c == "deploy" or c.startswith("pages deploy site/ "), c


def test_our_worker_config_is_the_one_deployed():
    assert 'name = "ai247-live"' in (ROOT / "worker/wrangler.toml").read_text().splitlines()
