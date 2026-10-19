"""Shared workspace: the blackboard every agent reads and writes.

Three things live here:
  1. Artifacts   every handoff payload, saved as JSON with who made it
                 and which artifacts it was derived from (lineage).
  2. Handoff log every dispatch / return / reject / escalate / gate / merge,
                 as one JSON line. This is what you study to learn the flow.
  3. Repo        a tiny version-tracked file store with per-task branches
                 and a serial merge queue (a stand-in for git worktrees).
"""

import asyncio
import json
import time
from pathlib import Path

COLORS = {
    "dispatch": "\033[36m", "return": "\033[32m", "accept": "\033[32m",
    "reject": "\033[33m", "escalate": "\033[31m", "gate": "\033[35m",
    "merge": "\033[34m", "skip": "\033[90m",
}
ARROWS = {
    "dispatch": "->", "return": "<-", "accept": "ok", "reject": "x ",
    "escalate": "^^", "gate": "<>", "merge": "=>", "skip": "--",
}
RESET = "\033[0m"


class Workspace:
    def __init__(self, root, quiet=False):
        self.root = Path(root)
        (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.root / "main").mkdir(exist_ok=True)
        self.quiet = quiet
        self.t0 = time.monotonic()
        self.events = []
        self.levels = {"you": -1}
        self.counts = {}
        self.artifacts = {}
        self.main_versions = {}
        self.branches = {}
        self.merge_lock = asyncio.Lock()

    def now(self):
        return round(time.monotonic() - self.t0, 3)

    def register(self, agent, level):
        self.levels[agent] = level

    # ---------- artifacts ----------
    def save(self, kind, data, by, parents=()):
        self.counts[kind] = self.counts.get(kind, 0) + 1
        aid = f"{kind}-{self.counts[kind]}"
        rec = {"id": aid, "kind": kind, "by": by, "parents": list(parents), "t": self.now(), "data": data}
        self.artifacts[aid] = rec
        (self.root / "artifacts" / f"{aid}.json").write_text(json.dumps(rec, indent=2))
        return aid

    def get(self, aid):
        return self.artifacts[aid]

    def data(self, aid):
        return self.artifacts[aid]["data"]

    # ---------- handoff log ----------
    def handoff(self, frm, to, kind, artifacts=(), note=""):
        ev = {"type": "handoff", "t": self.now(), "from": frm, "to": to, "kind": kind,
              "artifacts": list(artifacts), "note": note}
        self._emit(ev)
        if not self.quiet:
            depth = max(self.levels.get(frm, 0), 0)
            pad = "  " * depth
            arts = f" [{', '.join(artifacts)}]" if artifacts else ""
            msg = f" {note}" if note else ""
            print(f"{ev['t']:7.2f}s {pad}{COLORS[kind]}{ARROWS[kind]} {kind:<8}{RESET} "
                  f"{frm} -> {to}{arts}{msg}")

    def span(self, agent, label, start, end, ok=True):
        self._emit({"type": "span", "agent": agent, "label": label, "start": start, "end": end, "ok": ok})

    def _emit(self, ev):
        self.events.append(ev)
        with open(self.root / "handoffs.jsonl", "a") as f:
            f.write(json.dumps(ev) + "\n")

    # ---------- repo: branches + merge queue ----------
    def branch(self, task_id, files):
        """Fork a branch. Remember the main version of each file we will touch."""
        self.branches[task_id] = {"base": {p: self.main_versions.get(p, 0) for p in files}, "files": {}}

    def write_branch(self, task_id, files):
        self.branches[task_id]["files"] = {f["path"]: f["content"] for f in files}

    async def merge(self, task_id, by):
        """Serial merge queue. Detect conflicts by comparing file versions."""
        async with self.merge_lock:
            br = self.branches[task_id]
            conflicts = [p for p, v in br["base"].items() if self.main_versions.get(p, 0) != v]
            if conflicts:
                return conflicts
            await asyncio.sleep(0.05)  # pretend a rebase + fast-forward takes time
            for path, content in br["files"].items():
                out = self.root / "main" / path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(content)
                self.main_versions[path] = self.main_versions.get(path, 0) + 1
            self.handoff(by, "main", "merge", note=f"{task_id}: {len(br['files'])} file(s)")
            return []

    def snapshot_main(self):
        return {p: (self.root / "main" / p).read_text() for p in sorted(self.main_versions)}

    def write_trace(self):
        (self.root / "trace.json").write_text(json.dumps({"levels": self.levels, "events": self.events}, indent=1))
