# agent-foundry

A team of agents that turns requirements into a product.
Built to learn one thing well: how agents hand work to each other, and how orchestrators check that work at every level.

## Run it (no API key needed)

```bash
python -m foundry "Build a habit tracker"
```

Then open `runs/<timestamp>/trace.html`.

Useful flags:

| Flag | What it does |
|---|---|
| `--pool 5` | Max engineers working in parallel. Try 1 vs 3 and compare run time. |
| `--gates` | Pause for your approval at the PRD and design gates. |
| `--llm anthropic` | Use real Claude. Needs `pip install anthropic` and `ANTHROPIC_API_KEY`. |
| `--speed 3` | Scripted mode only. Makes fake agents faster. |

## The team

```
you
 └─ product-orchestrator          (level 0)  owns the PRD, runs the gates
     ├─ design-lead               (level 1)  ux-designer, ui-designer
     ├─ eng-lead                  (level 1)  architect, tech-planner, pool of frontend/backend devs
     └─ qa-lead                   (level 1)  pool of qa-engineers, integration-tester
```

## The handoff chain

Each level turns the artifact above it into the one below it.

```
requirements -> prd -> ux_flows + ui_mocks -> api_contract -> task_plan -> code_change -> qa_report -> main
```

## Where to read the code (in this order)

1. `foundry/agents.py`, `Lead.delegate`. The core loop: dispatch, check, accept or reject, retry 3 times, escalate.
2. `foundry/leads.py`. Each lead's checks. All plain code, no LLM. This is "verify against the contract above".
3. `foundry/leads.py`, `EngLead.build`. The parallel pool: dependency graph, file locks, free engineer slots.
4. `foundry/workspace.py`. Artifacts with lineage, the handoff log, branches and the serial merge queue.
5. `foundry/registry.py`. Agent cards. Add a specialist here without touching any lead.

## Planted mistakes (scripted mode)

So you can watch each feedback loop fire:

1. `ui-designer` forgets screen S3. The design lead rejects it.
2. The frontend dev on T5 edits a file it does not own. The eng lead rejects it before QA.
3. The backend dev on T3 skips input validation. QA fails it. The eng lead sends it back with QA's notes.

## Ideas to extend

- Make `tech-planner` plant a dependency cycle and watch the plan check catch it.
- Let `--gates` feedback reach the design lead, not just the PRD writer.
- Swap the fake repo for real `git worktree` branches.
- Give leads an LLM "judgment" step for things code checks cannot catch.
- When a task escalates, let the orchestrator re-plan instead of stopping.
