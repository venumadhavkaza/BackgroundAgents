"""Workers and the core handoff loop every lead uses.

The one function to understand in this whole project is `Lead.delegate`:

    dispatch -> worker runs -> schema check -> lead's own check
        pass  -> accept, return artifact id upward
        fail  -> reject with concrete feedback, retry (max 3)
        3 fails -> escalate to the parent lead
"""

import json

from .schemas import SCHEMAS, validate

MAX_RETRIES = 3


class Escalation(Exception):
    def __init__(self, frm, reason):
        super().__init__(f"{frm}: {reason}")
        self.frm = frm
        self.reason = reason


class Worker:
    """A worker sees only the inputs it was handed. Nothing else."""

    def __init__(self, card, llm, instance=None):
        self.card = card
        self.llm = llm
        self.name = instance or card.name

    def build_prompt(self, inputs, feedback):
        parts = ["## Your inputs (handed off by your lead)"]
        for key, val in inputs.items():
            parts.append(f"### {key}\n```json\n{json.dumps(val, indent=1)}\n```")
        if feedback:
            parts.append("## Your lead rejected your last attempt. Fix exactly these:")
            parts += [f"- {f}" for f in feedback]
        parts.append(f"Produce the `{self.card.produces}` artifact by calling the submit tool.")
        return "\n\n".join(parts)

    async def run(self, inputs, feedback, attempt):
        return await self.llm.produce(
            role=self.card.role, model=self.card.model, system=self.card.system,
            prompt=self.build_prompt(inputs, feedback), kind=self.card.produces,
            schema=SCHEMAS[self.card.produces], inputs=inputs, feedback=feedback, attempt=attempt,
        )


class Lead:
    """Base orchestrator. Leads plan, dispatch and check. They never do the work."""

    level = 1
    name = "lead"
    parent = "product-orchestrator"

    def __init__(self, ws, llm):
        self.ws = ws
        self.llm = llm
        ws.register(self.name, self.level)

    async def delegate(self, card, inputs, check=lambda d: [], *, instance=None, feedback=None):
        """Hand inputs to a worker and keep sending it back until the output passes."""
        worker = Worker(card, self.llm, instance)
        self.ws.register(worker.name, self.level + 1)
        payload = {k: self.ws.data(v) for k, v in inputs.items()}
        last_errs = []
        for attempt in range(1, MAX_RETRIES + 1):
            self.ws.handoff(self.name, worker.name, "dispatch", list(inputs.values()),
                            note=f"attempt {attempt}" if attempt > 1 else "")
            start = self.ws.now()
            data = await worker.run(payload, feedback, attempt)
            errs = validate(card.produces, data) or check(data)
            self.ws.span(worker.name, card.produces, start, self.ws.now(), ok=not errs)
            aid = self.ws.save(card.produces, data, by=worker.name, parents=inputs.values())
            self.ws.handoff(worker.name, self.name, "return", [aid])
            if not errs:
                self.ws.handoff(self.name, self.name, "accept", [aid])
                return aid
            self.ws.handoff(self.name, worker.name, "reject", [aid], note="; ".join(errs[:2]))
            feedback = errs
            last_errs = errs
        self.ws.handoff(self.name, self.parent, "escalate",
                        note=f"{worker.name} failed {MAX_RETRIES}x: {last_errs[0]}")
        raise Escalation(self.name, f"{worker.name} could not produce a valid {card.produces}")
