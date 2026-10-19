"""Offline fake LLM responses for a demo product: a habit tracker.

Three mistakes are planted on purpose so you can watch the feedback loops:
  1. ui-designer forgets screen S3 on its first try    -> design lead rejects
  2. frontend dev on T5 writes a file it does not own  -> eng lead rejects
  3. backend dev on T3 skips input validation          -> QA fails it, eng lead re-dispatches
"""

PRD = {
    "title": "Streaks, a tiny habit tracker",
    "problem": "People drop new habits because they cannot see progress day to day.",
    "users": ["Individuals building daily habits"],
    "features": [
        {"id": "F1", "name": "Create habit", "description": "Add a habit with a name and daily goal.",
         "acceptance_criteria": ["Name is required, 1 to 60 chars", "Habit appears in list after save"]},
        {"id": "F2", "name": "Daily check-in", "description": "Mark a habit done for today.",
         "acceptance_criteria": ["One check-in per habit per day", "Check-in is reflected instantly"]},
        {"id": "F3", "name": "Streak view", "description": "See current and best streak per habit.",
         "acceptance_criteria": ["Current streak resets after a missed day", "Best streak never decreases"]},
    ],
    "out_of_scope": ["Social sharing", "Reminders"],
}

UX = {
    "screens": [
        {"id": "S1", "name": "Habit list", "purpose": "See all habits and check in", "feature_ids": ["F1", "F2", "F3"],
         "elements": ["habit rows", "check-in button", "streak badge", "add button"]},
        {"id": "S2", "name": "New habit", "purpose": "Create a habit", "feature_ids": ["F1"],
         "elements": ["name input", "save button"]},
        {"id": "S3", "name": "Habit detail", "purpose": "Inspect streak history", "feature_ids": ["F2", "F3"],
         "elements": ["current streak", "best streak", "30 day grid"]},
    ],
    "flows": [
        {"name": "First habit", "steps": ["S1 empty state", "tap add", "S2 enter name", "save", "back to S1"]},
        {"name": "Daily check-in", "steps": ["S1", "tap check", "badge increments"]},
    ],
}

CONTRACT = {
    "data_models": [
        {"name": "Habit", "fields": ["id: uuid", "name: str", "created_at: date"]},
        {"name": "CheckIn", "fields": ["habit_id: uuid", "day: date"]},
    ],
    "endpoints": [
        {"method": "POST", "path": "/habits", "request": "{name}", "response": "Habit", "feature_ids": ["F1"]},
        {"method": "GET", "path": "/habits", "request": "", "response": "Habit[] with streaks", "feature_ids": ["F1", "F3"]},
        {"method": "POST", "path": "/habits/{id}/checkins", "request": "{day}", "response": "CheckIn", "feature_ids": ["F2"]},
        {"method": "GET", "path": "/habits/{id}/streak", "request": "", "response": "{current, best}", "feature_ids": ["F3"]},
    ],
}

PLAN = {
    "tasks": [
        {"id": "T1", "title": "Data models", "role": "backend", "files": ["backend/models.py"], "depends_on": [], "feature_ids": []},
        {"id": "T2", "title": "Habits API", "role": "backend", "files": ["backend/api_habits.py"], "depends_on": ["T1"], "feature_ids": ["F1"]},
        {"id": "T3", "title": "Check-ins and streak API", "role": "backend", "files": ["backend/api_checkins.py"], "depends_on": ["T1"], "feature_ids": ["F2", "F3"]},
        {"id": "T4", "title": "Habit list screen", "role": "frontend", "files": ["frontend/HabitList.jsx"], "depends_on": [], "feature_ids": ["F1", "F2"]},
        {"id": "T5", "title": "New habit screen", "role": "frontend", "files": ["frontend/NewHabit.jsx"], "depends_on": [], "feature_ids": ["F1"]},
        {"id": "T6", "title": "Habit detail screen", "role": "frontend", "files": ["frontend/HabitDetail.jsx"], "depends_on": [], "feature_ids": ["F3"]},
    ]
}


def mock_html(screen):
    items = "".join(f"<li style='padding:6px 0'>{e}</li>" for e in screen["elements"])
    return (f"<div style='font-family:sans-serif;max-width:360px;padding:16px;border:1px solid #ccc;"
            f"border-radius:12px'><h2>{screen['name']}</h2><ul>{items}</ul></div>")


def code_for(task, feedback):
    fixed = bool(feedback)
    files = []
    for path in task["files"]:
        if path.endswith(".py"):
            body = f'"""{task["title"]} (task {task["id"]})"""\n'
            if task["id"] == "T3" and fixed:
                body += "\ndef validate_day(day):\n    if day is None:\n        raise ValueError('day required')\n"
            body += "\n# endpoint handlers per api_contract\n"
        else:
            body = f"// {task['title']} (task {task['id']})\nexport default function Screen() {{ return null }}\n"
        files.append({"path": path, "content": body})
    if task["id"] == "T5" and not fixed:
        files.append({"path": "frontend/HabitList.jsx", "content": "// sneaky shared edit"})
    return {"task_id": task["id"], "files": files,
            "notes": "addressed lead feedback" if fixed else "first pass"}


def respond(*, role, kind, inputs, feedback, attempt):
    if kind == "prd":
        return PRD
    if kind == "ux_flows":
        return UX
    if kind == "ui_mocks":
        screens = UX["screens"] if attempt > 1 else UX["screens"][:2]
        return {"mocks": [{"screen_id": s["id"], "html": mock_html(s)} for s in screens]}
    if kind == "api_contract":
        return CONTRACT
    if kind == "task_plan":
        return PLAN
    if kind == "code_change":
        return code_for(inputs["task"], feedback)
    if kind == "qa_report":
        task, change = inputs["task"], inputs["code_change"]
        code = "".join(f["content"] for f in change["files"])
        if task["id"] == "T3" and "validate" not in code:
            return {"task_id": task["id"], "passed": False,
                    "issues": [{"severity": "high", "description": "POST /habits/{id}/checkins does not validate day"}]}
        return {"task_id": task["id"], "passed": True, "issues": []}
    if kind == "integration_report":
        return {"passed": True, "issues": []}
    raise ValueError(kind)
