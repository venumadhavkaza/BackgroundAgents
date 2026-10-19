"""LLM backends.

Workers call `produce()` and always get back a dict shaped like the
artifact they are supposed to hand off. Two backends:

  ScriptedLLM   offline, deterministic, no API key. Great for learning the
                orchestration flow. It deliberately makes a few mistakes so
                you can watch leads reject and retry.
  AnthropicLLM  real Claude calls. Structured output is enforced by forcing
                a single tool call whose input_schema is the artifact schema.
"""

import asyncio
import json
import random

from . import scripted


class ScriptedLLM:
    def __init__(self, speed=1.0, seed=7):
        self.speed = speed
        self.rng = random.Random(seed)

    async def produce(self, *, role, model, system, prompt, kind, schema, inputs, feedback, attempt):
        await asyncio.sleep(self.rng.uniform(0.3, 0.9) / self.speed)
        return scripted.respond(role=role, kind=kind, inputs=inputs, feedback=feedback, attempt=attempt)


class AnthropicLLM:
    def __init__(self):
        import anthropic  # pip install anthropic

        self.client = anthropic.AsyncAnthropic()

    async def produce(self, *, role, model, system, prompt, kind, schema, inputs, feedback, attempt):
        tool = {
            "name": f"submit_{kind}",
            "description": f"Submit the finished {kind} artifact for your lead to review.",
            "input_schema": schema,
        }
        msg = await self.client.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        for block in msg.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError(f"{role} returned no {kind}: {json.dumps([b.type for b in msg.content])}")
