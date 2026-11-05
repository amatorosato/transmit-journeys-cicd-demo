"""Turn a journey into readable "path = value" lines for the Terraform plan.

Called by data "external" in main.tf with {"journey": "<the journey as JSON>"} (or {"connection": …} for an
external connection) on stdin; prints a flat JSON map of strings. The plan then shows only the fields that change, e.g.
  ~ "Display Information #a57b0299 › action › title" = "`Signed in`" -> "`Welcome back`"
Forms (form_schema) are split per field: "Collect Information #… › form › title1 › label".
Standard library only: it runs on the HCP Terraform workers during plan.
"""
import json
import re
import sys

SEP = " › "


def scalar(v):
    return v if isinstance(v, str) else json.dumps(v)


def form_fields(text, path, out):
    """form_schema is a JSON-like list (values are `expressions`): one entry per field, keyed by its name."""
    blocks, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("{"):
            cur = []
        elif s.startswith("}"):
            if cur is not None:
                blocks.append(cur)
            cur = None
        elif cur is not None:
            m = re.match(r'"([^"]+)"\s*:\s*(.*?),?$', s)
            if m:
                cur.append((m.group(1), m.group(2)))
    if not blocks:
        return False
    for i, b in enumerate(blocks, 1):
        d = dict(b)
        name = d.get("name", "").strip('"') or f'{d.get("type", "item").strip(chr(34))} {i}'
        for k, v in b:
            if k != "name":
                out[SEP.join(path + ["form", name, k])] = v
    return True


def walk(obj, path, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, path + [k], out)
    elif isinstance(obj, list):
        if not obj:
            out[SEP.join(path)] = "[]"
        for i, v in enumerate(obj, 1):
            walk(v, path + [f"[{i}]"] if len(obj) > 1 else path, out)
    elif isinstance(obj, str) and "\n" in obj:
        if not (path and path[-1] == "value" and "form_schema" in path and form_fields(obj, path[:-2], out)):
            for i, line in enumerate(obj.splitlines(), 1):
                out[SEP.join(path + [f"line {i:03d}"])] = line
    else:
        out[SEP.join(path)] = scalar(obj)


def flatten(journey):
    out = {}
    versions = journey.get("versions") or []
    for vi, version in enumerate(versions, 1):
        vp = [f"version {vi}"] if len(versions) > 1 else []
        for k, v in version.items():
            if k == "workflow":
                for step in v.get("steps", []):
                    data = step.get("data", {})
                    label = f'{data.get("ui_name", step.get("type", "step"))} #{str(data.get("id", ""))[:8]}'
                    rest = {k2: v2 for k2, v2 in data.items() if k2 not in ("ui_name", "id")}
                    walk(rest, vp + [label], out)
                    walk({k2: v2 for k2, v2 in step.items() if k2 != "data"}, vp + [label], out)
                walk({k2: v2 for k2, v2 in v.items() if k2 != "steps"}, vp + ["workflow"], out)
            else:
                walk(v, vp + ["settings", k], out)
    walk({k: v for k, v in journey.items() if k != "versions"}, ["journey"], out)
    return out


if __name__ == "__main__":
    query = json.load(sys.stdin)
    if "connection" in query:
        doc, out = json.loads(query["connection"]), {}
        walk(doc.get("data") or {}, [], out)
        walk({k: v for k, v in doc.items() if k != "data"}, ["export"], out)
    else:
        out = flatten(json.loads(query["journey"]))
    json.dump(out, sys.stdout, ensure_ascii=False)
