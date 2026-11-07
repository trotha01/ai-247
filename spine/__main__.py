"""python -m spine run CHANNEL --root DIR [--dry-run] [--max-blocks N] [--producer-only|--worker-only]
python -m spine check [CHANNEL ...]        # validate channel YAMLs (default: every channels/*.yaml)

CHANNEL is a name (channels/<name>.yaml) or a path to a YAML file."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import CHANNELS, Runner, install_signals, load_channel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spine", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a channel forever (or until --max-blocks)")
    r.add_argument("channel")
    r.add_argument("--root", type=Path, required=True, help="channel state folder (inbox/, work/, failed/, state/ ...)")
    r.add_argument("--dry-run", action="store_true", help="every node runs, publish does not upload")
    r.add_argument("--max-blocks", type=int, default=0, help="stop after this many published blocks (0 = forever)")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--producer-only", action="store_true")
    g.add_argument("--worker-only", action="store_true")
    c = sub.add_parser("check", help="validate channel YAMLs")
    c.add_argument("channels", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        refs = a.channels or sorted(str(p) for p in CHANNELS.glob("*.yaml"))
        for ref in refs:
            ch = load_channel(ref)
            print(f"ok {ch['_path']}: {ch['channel']} prefix={ch['prefix']!r} " +
                  " | ".join(f"{st}: {','.join(n['node'] for n in ch[st])}" for st in ("producer", "item", "block")))
        return 0
    runner = Runner(load_channel(a.channel), a.root.resolve(), dry_run=a.dry_run, max_blocks=a.max_blocks)
    install_signals(runner)
    return runner.run(producer=not a.worker_only, worker=not a.producer_only)


if __name__ == "__main__":
    sys.exit(main())
