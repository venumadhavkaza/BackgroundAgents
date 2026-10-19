"""Handoff contracts.

Every artifact passed between levels has a schema. A lead never accepts
output that fails its schema, so a bad handoff is caught at the boundary
instead of three levels later.
"""

STR = {"type": "string"}
BOOL = {"type": "boolean"}


def ARR(items):
    return {"type": "array", "items": items}


def OBJ(**props):
    return {"type": "object", "properties": props, "required": list(props)}


ISSUE = OBJ(severity=STR, description=STR)

SCHEMAS = {
    "prd": OBJ(
        title=STR,
        problem=STR,
        users=ARR(STR),
        features=ARR(OBJ(id=STR, name=STR, description=STR, acceptance_criteria=ARR(STR))),
        out_of_scope=ARR(STR),
    ),
    "ux_flows": OBJ(
        screens=ARR(OBJ(id=STR, name=STR, purpose=STR, feature_ids=ARR(STR), elements=ARR(STR))),
        flows=ARR(OBJ(name=STR, steps=ARR(STR))),
    ),
    "ui_mocks": OBJ(mocks=ARR(OBJ(screen_id=STR, html=STR))),
    "api_contract": OBJ(
        data_models=ARR(OBJ(name=STR, fields=ARR(STR))),
        endpoints=ARR(OBJ(method=STR, path=STR, request=STR, response=STR, feature_ids=ARR(STR))),
    ),
    "task_plan": OBJ(
        tasks=ARR(OBJ(id=STR, title=STR, role=STR, files=ARR(STR), depends_on=ARR(STR), feature_ids=ARR(STR)))
    ),
    "code_change": OBJ(task_id=STR, files=ARR(OBJ(path=STR, content=STR)), notes=STR),
    "qa_report": OBJ(task_id=STR, passed=BOOL, issues=ARR(ISSUE)),
    "integration_report": OBJ(passed=BOOL, issues=ARR(ISSUE)),
}


def validate(kind, data):
    """Return a list of schema errors (empty list means valid)."""
    errs = []
    _check(SCHEMAS[kind], data, kind, errs)
    return errs


def _check(schema, v, path, errs):
    t = schema["type"]
    if t == "object":
        if not isinstance(v, dict):
            errs.append(f"{path}: expected object")
            return
        for k in schema.get("required", []):
            if k not in v:
                errs.append(f"{path}.{k}: missing")
        for k, sub in schema["properties"].items():
            if k in v:
                _check(sub, v[k], f"{path}.{k}", errs)
    elif t == "array":
        if not isinstance(v, list):
            errs.append(f"{path}: expected array")
            return
        for i, x in enumerate(v):
            _check(schema["items"], x, f"{path}[{i}]", errs)
    elif t == "string" and not isinstance(v, str):
        errs.append(f"{path}: expected string")
    elif t == "boolean" and not isinstance(v, bool):
        errs.append(f"{path}: expected boolean")
