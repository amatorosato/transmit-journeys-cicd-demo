"""Copy journeys and external connections from a tenant export into Git (console -> Git).

Journeys captured: every journey already in journeys/, the journeys named with --journeys, and every journey whose
id starts with --prefix.
External connections captured (into connections/<provider_id>.yaml): every connection already in connections/, the
ones named with --connections (name or id), and every connection used by a journey in journeys/ (web request
functions are called by name: `ns: webrequests`, `function: <name>`; other connections by their id).
Files are written exactly as exported (minus last_modified_date), so they match what the drift check compares.
Soft delete: a journey in Git that is no longer on the tenant (deleted in the dev console) is not removed from Git:
its file becomes a tombstone renamed DELETED-<name> (only the `name:` line changes; the journey stays active). Once
merged, it is promoted dev -> test -> prod like any change, so the journey is renamed on every tenant instead of deleted. Connections in Git
but missing on the tenant are reported, never deleted. Secrets are not exported: connections refer to
credentials by alias, which must exist on every tenant the connection is deployed to; they are listed in --notes.
Usage: python3 scripts/capture.py <export.zip> [--journeys "A,B"] [--prefix CICD-] [--connections "X,Y"]
                                  [--notes notes.md] [--summary summary.md]
--summary: markdown report of what was found (new, changed, deleted, unchanged), for the run page and the pull request.
"""
import argparse
import difflib
import glob
import os
import re
import zipfile

import yaml

ap = argparse.ArgumentParser()
ap.add_argument("export")
ap.add_argument("--journeys", default="")
ap.add_argument("--prefix", default="")
ap.add_argument("--connections", default="")
ap.add_argument("--notes", default="")
ap.add_argument("--summary", default="")
a = ap.parse_args()

z = zipfile.ZipFile(a.export)


def entities(folder):
    return {os.path.basename(n)[:-5]: n for n in z.namelist()
            if re.search(rf"/ido/{folder}/[^/]+\.yaml$", n) and not n.endswith("/manifest.yaml")}


changes = []      # (status, type, name, detail) for the summary
unchanged = []    # (type, name)
warnings = []


def write(path, text, kind, name, detail=""):
    text = re.sub(r"^last_modified_date: .*\n", "", text, flags=re.M)   # changes on every save
    old = open(path).read() if os.path.exists(path) else None
    if old != text:
        open(path, "w").write(text)
        print(("updated " if old else "added   ") + path)
        if old is None:
            changes.append(("✨ New", kind, name, detail or f"`{path}`"))
        else:
            diff = [l for l in difflib.unified_diff(old.splitlines(), text.splitlines(), lineterm="", n=0)
                    if l[:1] in "+-" and not l.startswith(("+++", "---"))]
            lines = len([l for l in diff if l.startswith("+")]) or len(diff)
            changes.append(("✏️ Changed", kind, name, f"{lines} line{'s' if lines != 1 else ''} changed" +
                            (f"; {detail}" if detail else "")))
    else:
        print(f"same    {path}")
        unchanged.append((kind, name))


def split(value):
    return {x.strip() for x in value.split(",") if x.strip()}


# --- journeys
PREFIX_DELETED = "DELETED-"
deleted = []   # (old name, new name)
live = entities("journeys")
wanted = {os.path.basename(p)[:-5] for p in glob.glob("journeys/*.yaml")} | split(a.journeys)
if a.prefix:
    wanted |= {j for j in live if j.startswith(a.prefix)}
os.makedirs("journeys", exist_ok=True)
for j in sorted(wanted):
    if j not in live:
        path = f"journeys/{j}.yaml"
        if not os.path.exists(path):
            print(f"::warning::journey {j}: requested, but not on the tenant")
            warnings.append(f"Journey `{j}` was requested, but it is not on the dev tenant.")
            continue
        text = open(path).read()
        m = re.search(r"^name: (.*)$", text, re.M)
        name = (yaml.safe_load(text) or {}).get("name") or j
        if m and not name.startswith(PREFIX_DELETED):
            text = text[:m.start()] + "name: " + yaml.safe_dump(PREFIX_DELETED + name).split("\n")[0] + text[m.end():]
            open(path, "w").write(text)
            deleted.append((name, PREFIX_DELETED + name))
            changes.append(("🗑️ Deleted in the console", "Journey", name,
                            f"renamed `{PREFIX_DELETED}{name}`: stays deleted on the dev tenant, renamed on test and prod"))
            print(f"deleted {path}: not on the tenant any more, renamed {PREFIX_DELETED}{name} (soft delete)")
        elif name.startswith(PREFIX_DELETED):
            unchanged.append(("Journey", name + " (deleted)"))
        continue
    text = z.read(live[j]).decode()
    write(f"journeys/{j}.yaml", text, "Journey", (yaml.safe_load(text) or {}).get("name") or j)

# --- external connections
conns = {}
for cid, n in entities("external-connections").items():
    text = z.read(n).decode()
    data = (yaml.safe_load(text) or {}).get("data") or {}
    conns[cid] = {"text": text, "name": data.get("name") or cid, "data": data}
by_name = {c["name"]: cid for cid, c in conns.items()}

journey_text = "\n".join(open(p).read() for p in glob.glob("journeys/*.yaml"))
journey_texts = {(yaml.safe_load(open(p)) or {}).get("name") or p: open(p).read() for p in glob.glob("journeys/*.yaml")}


def used_by(cid):
    name = conns[cid]["name"]
    users = [j for j, t in journey_texts.items()
             if cid in t or re.search(rf"function:\s*['\"]?{re.escape(name)}['\"]?\s*$", t, re.M)]
    return "used by " + ", ".join(sorted(users)) if users else ""
used = {by_name[f] for f in re.findall(r"function:\s*['\"]?([\w.\-]+)", journey_text) if f in by_name}
used |= {cid for cid in conns if cid in journey_text}
wanted_c = {os.path.basename(p)[:-5] for p in glob.glob("connections/*.yaml")} | used
for x in split(a.connections):
    if x in conns or x in by_name:
        wanted_c.add(by_name.get(x, x))
    else:
        print(f"::warning::connection {x}: not on the tenant")
        warnings.append(f"External connection `{x}` was requested, but it is not on the dev tenant.")

aliases = set()
for cid in sorted(wanted_c):
    if cid not in conns:
        print(f"::warning::connection {cid}: in Git, but not on the tenant (not deleted)")
        warnings.append(f"External connection `{cid}` is in Git but no longer on the dev tenant (kept in Git).")
        continue
    os.makedirs("connections", exist_ok=True)
    write(f"connections/{cid}.yaml", conns[cid]["text"], "External connection", conns[cid]["name"], used_by(cid))

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") in ("credentials", "keys", "certificates") and "alias" in o:
                aliases.add((conns[cid]["name"], o["type"], o["alias"], str(o.get("version", ""))))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(conns[cid]["data"].get("config"))

if a.notes:
    with open(a.notes, "w") as f:
        if deleted:
            f.write("**Deleted in the dev tenant console:** " + ", ".join(o for o, _ in deleted) + ". They are not deleted "
                    "anywhere: each one is renamed with the prefix `DELETED-` (" + ", ".join(n for _, n in deleted) +
                    "). The journey stays active: apps calling it by id still run it. After the merge the rename is promoted "
                    "like any change: the dev tenant gets the renamed journey back, then the test and prod tenants after "
                    "Confirm & apply. To bring one back, remove the prefix in a pull request. To remove it for good, "
                    "delete it in each tenant console and remove its file from Git.\n\n")
        if aliases:
            f.write("**Secrets needed on the test and prod tenants** (they are not exported: create them with the "
                    "same alias and version, or the deploy stops at validate with `MISSING_CREDENTIALS`):\n\n")
            f.writelines(f"- `{al}` (version {v}), {t}, used by {n}\n" for n, t, al, v in sorted(aliases))

if a.summary:
    with open(a.summary, "w") as f:
        f.write("### What Capture from dev found on the dev tenant\n\n")
        if changes:
            f.write(f"**{len(changes)} change{'s' if len(changes) != 1 else ''}** to bring into Git:\n\n"
                    "| | Type | Name | Details |\n|---|---|---|---|\n")
            f.writelines(f"| {st} | {k} | {n} | {d} |\n" for st, k, n, d in changes)
        else:
            f.write("**No changes:** everything in Git matches the dev tenant.\n")
        if unchanged:
            j = sorted(n for k, n in unchanged if k == "Journey")
            c = sorted(n for k, n in unchanged if k != "Journey")
            f.write("\n**Unchanged:** " + "; ".join(x for x in (
                f"{len(j)} journey{'s' if len(j) != 1 else ''} ({', '.join(j)})" if j else "",
                f"{len(c)} external connection{'s' if len(c) != 1 else ''} ({', '.join(c)})" if c else "") if x) + "\n")
        if warnings:
            f.write("\n**Warnings:**\n\n" + "".join(f"- {w}\n" for w in warnings))
