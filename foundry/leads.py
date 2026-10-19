"""The orchestrators.

    ProductOrchestrator (level 0)
      ├─ DesignLead   (level 1)  ux-designer, ui-designer
      ├─ EngLead      (level 1)  architect, tech-planner, N x frontend/backend devs
      └─ QALead       (level 1)  N x qa-engineer, integration-tester

Every check below is plain code, not an LLM. Leads verify output against
the artifact one level up (PRD -> design -> contract -> code). That is what
makes the handoffs trustworthy.
"""

import asyncio

from .agents import MAX_RETRIES, Escalation, Lead
from .registry import pick


def feature_ids(prd):
    return {f["id"] for f in prd["features"]}


def find_cycle(tasks):
    graph = {t["id"]: t["depends_on"] for t in tasks}
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(visit(d) for d in graph.get(n, [])):
            return True
        state[n] = 2
        return False

    return any(visit(n) for n in graph)


# ------------------------------------------------------------------ design
class DesignLead(Lead):
    name = "design-lead"

    async def run(self, prd_id):
        prd = self.ws.data(prd_id)
        want = feature_ids(prd)

        def check_ux(ux):
            covered = {f for s in ux["screens"] for f in s["feature_ids"]}
            errs = [f"feature {f} is not on any screen" for f in sorted(want - covered)]
            errs += [f"screen references unknown feature {f}" for f in sorted(covered - want)]
            return errs

        ux_id = await self.delegate(pick("ux"), {"prd": prd_id}, check_ux)
        screens = {s["id"] for s in self.ws.data(ux_id)["screens"]}

        def check_mocks(m):
            have = {x["screen_id"] for x in m["mocks"] if x["html"].strip()}
            return [f"screen {s} has no mock" for s in sorted(screens - have)]

        mocks_id = await self.delegate(pick("ui"), {"prd": prd_id, "ux_flows": ux_id}, check_mocks)
        spec = {"ux_flows": self.ws.data(ux_id), "ui_mocks": self.ws.data(mocks_id)}
        return self.ws.save("design_spec", spec, by=self.name, parents=[ux_id, mocks_id])


# ------------------------------------------------------------------ QA
class QALead(Lead):
    name = "qa-lead"

    async def review(self, requester, task_id_art, change_id, contract_id, prd_id, slot):
        """Paired QA. Called by the eng lead, handled by the QA lead's own worker."""
        self.ws.handoff(requester, self.name, "dispatch", [change_id], note="review request")
        task = self.ws.data(task_id_art)

        def check(r):
            return [] if r["task_id"] == task["id"] else [f"report is for {r['task_id']}, expected {task['id']}"]

        rep = await self.delegate(pick("qa"),
                                  {"task": task_id_art, "code_change": change_id,
                                   "api_contract": contract_id, "prd": prd_id},
                                  check, instance=f"qa-engineer#{slot}")
        self.ws.handoff(self.name, requester, "return", [rep])
        return rep

    async def integrate(self, prd_id, contract_id):
        code_id = self.ws.save("codebase", self.ws.snapshot_main(), by="main")
        return await self.delegate(pick("integration"),
                                   {"prd": prd_id, "api_contract": contract_id, "codebase": code_id})


# ------------------------------------------------------------------ engineering
class EngLead(Lead):
    name = "eng-lead"

    def __init__(self, ws, llm, qa, pool_size=3):
        super().__init__(ws, llm)
        self.qa = qa
        self.pool_size = pool_size

    async def run(self, prd_id, design_id):
        prd = self.ws.data(prd_id)
        want = feature_ids(prd)

        def check_contract(c):
            covered = {f for e in c["endpoints"] for f in e["feature_ids"]}
            return [f"feature {f} has no endpoint" for f in sorted(want - covered)]

        self.contract_id = await self.delegate(pick("architect"), {"prd": prd_id, "design_spec": design_id},
                                               check_contract)

        def check_plan(p):
            ts = p["tasks"]
            ids = [t["id"] for t in ts]
            errs = [f"duplicate task id {i}" for i in set(ids) if ids.count(i) > 1]
            errs += [f"{t['id']} has bad role {t['role']}" for t in ts if t["role"] not in ("frontend", "backend")]
            errs += [f"{t['id']} owns no files" for t in ts if not t["files"]]
            errs += [f"{t['id']} depends on unknown {d}" for t in ts for d in t["depends_on"] if d not in ids]
            owners = {}
            for t in ts:
                for f in t["files"]:
                    if f in owners:
                        errs.append(f"{f} owned by both {owners[f]} and {t['id']}")
                    owners[f] = t["id"]
            if find_cycle(ts):
                errs.append("task dependencies contain a cycle")
            covered = {f for t in ts for f in t["feature_ids"]}
            errs += [f"feature {f} has no task" for f in sorted(want - covered)]
            return errs

        plan_id = await self.delegate(pick("planner"),
                                      {"prd": prd_id, "design_spec": design_id, "api_contract": self.contract_id},
                                      check_plan)
        return await self.build(self.ws.data(plan_id)["tasks"], prd_id, design_id)

    # ---- the parallel pool ----
    async def build(self, tasks, prd_id, design_id):
        pending = {t["id"]: t for t in tasks}
        running = {}           # asyncio.Task -> task dict
        done, failed = set(), set()
        locked = set()         # files currently being edited
        free = list(range(1, self.pool_size + 1))

        while pending or running:
            # 1. Dispatch every ready task while there is a free engineer.
            for tid, t in list(pending.items()):
                if not free:
                    break
                if set(t["depends_on"]) & failed:
                    del pending[tid]
                    failed.add(tid)
                    self.ws.handoff(self.name, self.name, "skip", note=f"{tid}: a dependency failed")
                    continue
                if set(t["depends_on"]) <= done and not (set(t["files"]) & locked):
                    del pending[tid]
                    locked |= set(t["files"])
                    slot = free.pop(0)
                    job = asyncio.create_task(self.build_task(t, slot, prd_id, design_id))
                    running[job] = (t, slot)
            if not running:
                raise Escalation(self.name, f"blocked tasks: {sorted(pending)}")

            # 2. Wait for whichever engineer finishes first.
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for job in finished:
                t, slot = running.pop(job)
                locked -= set(t["files"])
                free.append(slot)
                free.sort()
                if job.exception():
                    failed.add(t["id"])
                else:
                    done.add(t["id"])
        return {"done": sorted(done), "failed": sorted(failed)}

    async def build_task(self, t, slot, prd_id, design_id):
        card = pick(t["role"])
        inst = f"{card.name}#{slot}"
        task_art = self.ws.save("task", t, by=self.name)
        self.ws.branch(t["id"], t["files"])
        owned = set(t["files"])

        def check_change(c):
            touched = {f["path"] for f in c["files"]}
            errs = [f"wrote {p}, which {t['id']} does not own" for p in sorted(touched - owned)]
            errs += [f"missing owned file {p}" for p in sorted(owned - touched)]
            return errs

        inputs = {"task": task_art, "api_contract": self.contract_id, "design_spec": design_id}
        feedback = None
        for round_ in range(1, MAX_RETRIES + 1):
            change = await self.delegate(card, inputs, check_change, instance=inst, feedback=feedback)
            rep_id = await self.qa.review(self.name, task_art, change, self.contract_id, prd_id, slot)
            rep = self.ws.data(rep_id)
            if rep["passed"]:
                break
            issues = [i["description"] for i in rep["issues"]]
            self.ws.handoff(self.name, inst, "reject", [rep_id], note=f"QA: {issues[0]}")
            feedback = [f"QA failed your change: {i}" for i in issues]
        else:
            self.ws.handoff(self.name, self.parent, "escalate", note=f"{t['id']} failed QA {MAX_RETRIES}x")
            raise Escalation(self.name, f"{t['id']} failed QA")

        self.ws.write_branch(t["id"], self.ws.data(change)["files"])
        conflicts = await self.ws.merge(t["id"], by=self.name)
        if conflicts:
            self.ws.handoff(self.name, self.parent, "escalate", note=f"{t['id']} merge conflict {conflicts}")
            raise Escalation(self.name, f"merge conflict in {conflicts}")


# ------------------------------------------------------------------ top
class ProductOrchestrator(Lead):
    name = "product-orchestrator"
    level = 0
    parent = "you"

    def __init__(self, ws, llm, pool_size=3, auto_approve=True):
        super().__init__(ws, llm)
        self.auto = auto_approve
        self.design = DesignLead(ws, llm)
        self.qa = QALead(ws, llm)
        self.eng = EngLead(ws, llm, self.qa, pool_size)

    def gate(self, label, aid):
        """Human approval. Returns None to approve, or feedback text to redo."""
        self.ws.handoff(self.name, "you", "gate", [aid], note=f"approve {label}?")
        if self.auto:
            self.ws.handoff("you", self.name, "accept", [aid], note="auto-approved")
            return None
        path = self.ws.root / "artifacts" / f"{aid}.json"
        ans = input(f"\n  Review {path}\n  Approve {label}? [Enter = yes, or type feedback]: ").strip()
        if not ans or ans.lower() in ("y", "yes"):
            self.ws.handoff("you", self.name, "accept", [aid])
            return None
        self.ws.handoff("you", self.name, "reject", [aid], note=ans)
        return ans

    async def run(self, requirements):
        req = self.ws.save("requirements", {"text": requirements}, by="you")
        self.ws.handoff("you", self.name, "dispatch", [req])

        def check_prd(p):
            ids = [f["id"] for f in p["features"]]
            errs = [] if ids else ["PRD has no features"]
            errs += [f"duplicate feature id {i}" for i in set(ids) if ids.count(i) > 1]
            errs += [f"{f['id']} has no acceptance criteria" for f in p["features"] if not f["acceptance_criteria"]]
            return errs

        feedback = None
        for _ in range(MAX_RETRIES):
            prd = await self.delegate(pick("pm"), {"requirements": req}, check_prd, feedback=feedback)
            note = self.gate("PRD", prd)
            if note is None:
                break
            feedback = [f"Human reviewer: {note}"]

        for _ in range(MAX_RETRIES):
            self.ws.handoff(self.name, self.design.name, "dispatch", [prd])
            design = await self.design.run(prd)
            self.ws.handoff(self.design.name, self.name, "return", [design])
            if self.gate("design", design) is None:
                break

        self.ws.handoff(self.name, self.eng.name, "dispatch", [prd, design])
        result = await self.eng.run(prd, design)
        self.ws.handoff(self.eng.name, self.name, "return", note=f"merged {result['done']}, failed {result['failed']}")

        self.ws.handoff(self.name, self.qa.name, "dispatch", note="integration test main")
        report = await self.qa.integrate(prd, self.eng.contract_id)
        self.ws.handoff(self.qa.name, self.name, "return", [report])

        ok = self.ws.data(report)["passed"] and not result["failed"]
        self.ws.handoff(self.name, "you", "return", [report], note="SHIPPED" if ok else "needs attention")
        return {"ok": ok, **result, "report": report}
