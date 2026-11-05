"""Copy journeys and external connections from a tenant export into Git (console -> Git).

Journeys captured: every journey already in journeys/, the journeys named with --journeys, and every journey whose
id starts with --prefix.
External connections captured (into connections/<provider_id>.yaml): every connection already in connections/, the
ones named with --connections (name or id), and every connection used by a journey in journeys/ (web request
functions are called by name: `ns: webrequests`, `function: <name>`; other connections by their id).
Files are written exactly as exported (minus last_modified_date), so they match what the drift check compares.
Entities in Git but missing on the tenant are reported, never deleted. Secrets are not exported: connections refer to
credentials by alias, which must exist on every tenant the connection is deployed to; they are listed in --notes.
Usage: python3 scripts/capture.py <export.zip> [--journeys "A,B"] [--prefix CICD-] [--connections "X,Y"]
                                  [--notes notes.md]
"""
import argparse
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
a = ap.parse_args()

z = zipfile.ZipFile(a.export)


def entities(folder):
    return {os.path.basename(n)[:-5]: n for n in z.namelist()
            if re.search(rf"/ido/{folder}/[^/]+\.yaml$", n) and not n.endswith("/manifest.yaml")}


def write(path, text):
    text = re.sub(r"^last_modified_date: .*\n", "", text, flags=re.M)   # changes on every save
    old = open(path).read() if os.path.exists(path) else None
    if old != text:
        open(path, "w").write(text)
        print(("updated " if old else "added   ") + path)
    else:
        print(f"same    {path}")


def split(value):
    return {x.strip() for x in value.split(",") if x.strip()}


# --- journeys
live = entities("journeys")
wanted = {os.path.basename(p)[:-5] for p in glob.glob("journeys/*.yaml")} | split(a.journeys)
if a.prefix:
    wanted |= {j for j in live if j.startswith(a.prefix)}
os.makedirs("journeys", exist_ok=True)
for j in sorted(wanted):
    if j not in live:
        print(f"::warning::journey {j}: in Git or requested, but not on the tenant (not deleted)")
        continue
    write(f"journeys/{j}.yaml", z.read(live[j]).decode())

# --- external connections
conns = {}
for cid, n in entities("external-connections").items():
    text = z.read(n).decode()
    data = (yaml.safe_load(text) or {}).get("data") or {}
    conns[cid] = {"text": text, "name": data.get("name") or cid, "data": data}
by_name = {c["name"]: cid for cid, c in conns.items()}

journey_text = "\n".join(open(p).read() for p in glob.glob("journeys/*.yaml"))
used = {by_name[f] for f in re.findall(r"function:\s*['\"]?([\w.\-]+)", journey_text) if f in by_name}
used |= {cid for cid in conns if cid in journey_text}
wanted_c = {os.path.basename(p)[:-5] for p in glob.glob("connections/*.yaml")} | used
for x in split(a.connections):
    if x in conns or x in by_name:
        wanted_c.add(by_name.get(x, x))
    else:
        print(f"::warning::connection {x}: not on the tenant")

aliases = set()
for cid in sorted(wanted_c):
    if cid not in conns:
        print(f"::warning::connection {cid}: in Git, but not on the tenant (not deleted)")
        continue
    os.makedirs("connections", exist_ok=True)
    write(f"connections/{cid}.yaml", conns[cid]["text"])

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
        names = [conns[c]["name"] for c in sorted(wanted_c) if c in conns]
        if names:
            f.write("**External connections in Git:** " + ", ".join(names) + "\n\n")
        if aliases:
            f.write("**Secrets needed on the test and prod tenants** (they are not exported: create them with the "
                    "same alias and version, or the deploy stops at validate with `MISSING_CREDENTIALS`):\n\n")
            f.writelines(f"- `{al}` (version {v}), {t}, used by {n}\n" for n, t, al, v in sorted(aliases))
