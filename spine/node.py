"""Run one Python node function on a job folder:  python -m spine.node MODULE:FUNC JOB

Exit code 0 for ok/skip, 1 for fail; result.json in JOB is what the runner trusts, not the exit code."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .contract import call


def resolve(ref: str):
    mod, _, fn = ref.partition(":")
    if not mod or not fn:
        raise SystemExit(f"node ref must be MODULE:FUNC, not {ref!r}")
    return getattr(importlib.import_module(mod), fn)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit(__doc__)
    r = call(resolve(argv[0]), Path(argv[1]).resolve())
    return 0 if r["status"] in ("ok", "skip") else 1


if __name__ == "__main__":
    sys.exit(main())
