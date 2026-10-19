"""CLI.

    python -m foundry "Build a habit tracker"                       # offline demo
    python -m foundry "Build a habit tracker" --llm anthropic --gates  # real Claude, you approve gates
"""

import argparse
import asyncio
import time
from pathlib import Path

from .leads import ProductOrchestrator
from .llm import AnthropicLLM, ScriptedLLM
from .trace import render
from .workspace import Workspace


def main():
    ap = argparse.ArgumentParser(prog="foundry")
    ap.add_argument("requirements", nargs="?", default="Build a simple habit tracker with daily check-ins and streaks.")
    ap.add_argument("--llm", choices=["scripted", "anthropic"], default="scripted")
    ap.add_argument("--pool", type=int, default=3, help="max engineers working in parallel")
    ap.add_argument("--gates", action="store_true", help="pause for your approval at PRD and design")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--speed", type=float, default=1.0, help="scripted mode only: higher is faster")
    args = ap.parse_args()

    run_dir = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
    ws = Workspace(run_dir)
    llm = ScriptedLLM(speed=args.speed) if args.llm == "scripted" else AnthropicLLM()
    boss = ProductOrchestrator(ws, llm, pool_size=args.pool, auto_approve=not args.gates)

    print(f"\nRun dir: {run_dir}\n")
    try:
        result = asyncio.run(boss.run(args.requirements))
        print(f"\nResult: {'SHIPPED' if result['ok'] else 'NEEDS ATTENTION'}  "
              f"merged={result['done']} failed={result['failed']}")
    finally:
        ws.write_trace()
        html = render(run_dir / "trace.json", run_dir / "trace.html", args.requirements)
        print(f"Trace:  {html}\nCode:   {run_dir / 'main'}\n")


if __name__ == "__main__":
    main()
