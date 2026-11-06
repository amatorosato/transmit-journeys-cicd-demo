"""Describe journey and connection changes in words, with the same "step › field = value" view as the Terraform plan
(terraform/flatten.py). Used by capture.py and promotion.py.
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "terraform"))
import flatten as _flatten  # noqa: E402

SEP = " › "


def fields(kind, text):
    doc = yaml.safe_load(text) or {}
    if kind == "Journey":
        return _flatten.flatten(doc)
    out = {}
    _flatten.walk(doc.get("data") or {}, [], out)
    return out


def short(v, n=60):
    v = str(v).strip()
    if len(v) > 1 and v[0] == v[-1] == "`":     # journey texts are `template literals`
        v = v[1:-1]
    return v if len(v) <= n else v[:n - 1] + "…"


def explain(kind, old, new, limit=8):
    """Changes in words: steps added or removed, then fields changed (old -> new)."""
    fo, fn = fields(kind, old), fields(kind, new)
    if kind != "Journey":
        keys = sorted(set(fo) | set(fn))
        out = [f"✏️ **{k}**: `{short(fo.get(k, '(none)'))}` → `{short(fn.get(k, '(none)'))}`"
               for k in keys if fo.get(k) != fn.get(k)]
        return out[:limit] + ([f"… and {len(out) - limit} more fields"] if len(out) > limit else [])
    group = lambda d: {k.split(SEP)[0] for k in d}
    added, removed = group(fn) - group(fo), group(fo) - group(fn)

    def step_text(d, s):
        parts = [f"{f} `{short(d[k], 40)}`" for f in ("title", "text") for k in [f"{s}{SEP}action{SEP}{f}{SEP}value"] if k in d]
        return f" ({', '.join(parts)})" if parts else ""
    out = [f"➕ Added step **{s.split(' #')[0]}**{step_text(fn, s)}" for s in sorted(added)]
    out += [f"➖ Removed step **{s.split(' #')[0]}**{step_text(fo, s)}" for s in sorted(removed)]
    changed = [k for k in sorted(set(fo) | set(fn)) if k.split(SEP)[0] not in added | removed and fo.get(k) != fn.get(k)]
    out += [f"✏️ **{(k.split(' #')[0] + (SEP + k.split(SEP, 1)[1] if SEP in k else '')).replace(SEP + 'action' + SEP, SEP)}**: "
            f"`{short(fo.get(k, '(none)'))}` → `{short(fn.get(k, '(none)'))}`" for k in changed]
    return out[:limit] + ([f"… and {len(out) - limit} more changes"] if len(out) > limit else [])


def headline(lines):
    """One short line for the table: '1 step added, 2 fields changed'."""
    a = sum(l.startswith("➕") for l in lines)
    r = sum(l.startswith("➖") for l in lines)
    c = sum(l.startswith("✏️") for l in lines)
    parts = [f"{a} step{'s' if a != 1 else ''} added" if a else "", f"{r} step{'s' if r != 1 else ''} removed" if r else "",
             f"{c} field{'s' if c != 1 else ''} changed" if c else ""]
    return ", ".join(p for p in parts if p) or "formatting only"
