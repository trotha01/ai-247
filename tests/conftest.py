import json
import os
from pathlib import Path

import pytest

OUT = Path(os.environ.get("NEWSBOT_OUT", "out"))


@pytest.fixture(scope="session")
def out():
    if not (OUT / "manifest.json").exists():
        pytest.skip(f"no rendered bulletin in {OUT} (run python -m newsbot.pipeline first)")
    return OUT


@pytest.fixture(scope="session")
def manifest(out):
    return json.loads((out / "manifest.json").read_text())


@pytest.fixture(scope="session")
def script(out):
    return json.loads((out / "script.json").read_text())


@pytest.fixture(scope="session")
def plan(out):
    return json.loads((out / "plan.json").read_text())
