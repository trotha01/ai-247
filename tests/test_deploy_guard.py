"""Guard: no workflow deploys or runs anything under studio/ (Puddle Park; its owners deploy it by hand).

studio/cloudflare/*/wrangler.toml name other Workers and buckets on another Cloudflare account. If any workflow
ever ran wrangler there, or listed studio/ in its triggers or steps, our secrets would deploy someone else's
config. These checks read the workflow files as text (no YAML dependency) and ignore comment lines.
The rule lives here and in docs/DEPLOY.md, not in deploy.yml: editing deploy.yml triggers a production deploy.
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


PUDDLE = ROOT / ".github/workflows/deploy-puddle.yml"


def test_no_workflow_but_deploy_puddle_mentions_studio():
    hits = [f"{p.name}:{i}: {l.strip()}" for p in WORKFLOWS if p != PUDDLE
            for i, l in code_lines(p) if "studio" in l.lower()]
    assert not hits, "only deploy-puddle.yml may touch studio/:\n" + "\n".join(hits)


def test_deploy_puddle_is_gated_and_scoped():
    text = PUDDLE.read_text()
    lines = [l for _, l in code_lines(PUDDLE)]
    # triggers: main pushes under studio/cloudflare/ only, plus manual runs
    block = re.search(r"^  push:\n(?:    .*\n)+", text, re.M).group(0)
    assert re.findall(r'^      - "([^"]+)"', block, re.M) == ["studio/cloudflare/**"]
    assert "branches: [main]" in block and "pull_request" not in text
    # job runs only on main, and every deploy step needs the gate, which needs PUDDLE_DEPLOY_ENABLED == true
    assert "github.ref == 'refs/heads/main'" in text
    assert 'if [ "$ENABLED" != "true" ]' in text and "vars.PUDDLE_DEPLOY_ENABLED" in text
    steps = text.split("\n      - ")[1:]
    deploys = [s for s in steps if "wrangler-action" in s]
    assert len(deploys) == 2 and all("if: steps.gate.outputs.ready == 'true'" in s for s in deploys)
    wd = sorted(l.split(":", 1)[1].strip() for l in lines if re.match(r"\s*workingDirectory:", l))
    assert wd == ["studio/cloudflare/puddle-live", "studio/cloudflare/showrunner-link"], wd
    assert all(l.split(":", 1)[1].strip() == "deploy" for l in lines if re.match(r"\s*command:", l))


def test_puddle_configs_stay_in_the_shared_bucket_under_puddle():
    live = (ROOT / "studio/cloudflare/puddle-live/wrangler.toml").read_text().splitlines()
    link = (ROOT / "studio/cloudflare/showrunner-link/wrangler.toml").read_text().splitlines()
    assert 'name = "puddle-live"' in live and 'name = "puddle-showrunner"' in link  # never ai247-live or aitv-live
    assert 'bucket_name = "ai247-media"' in live and 'bucket_name = "ai247-media"' in link
    assert 'PREFIX = "puddle/"' in live
    keys = re.findall(r'BUCKET\.(?:get|put|head|delete)\("([^"]+)"', (ROOT / "studio/cloudflare/showrunner-link/src/index.js").read_text())
    assert keys and all(k.startswith("puddle/") for k in keys), keys
    for p in ROOT.glob("studio/**/*"):
        if p.is_file() and p.suffix in {".py", ".js", ".sh", ".toml", ".json", ""}:
            assert "mychalsimka" not in p.read_text(errors="ignore"), p


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
