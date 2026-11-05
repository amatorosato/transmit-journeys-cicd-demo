"""Copy journeys from a tenant export into journeys/ (console -> Git).

Captured: every journey already in journeys/, the journeys named with --journeys, and every journey whose
id starts with --prefix. Files are written exactly as exported (minus last_modified_date), so they match
what the drift check compares. Journeys in Git but missing on the tenant are reported, never deleted.
Usage: python3 scripts/capture.py <export.zip> [--journeys "A,B"] [--prefix CICD-] [--only]
--only: capture just the journeys named with --journeys (used by the drift check).
"""
import argparse
import glob
import os
import re
import zipfile

ap = argparse.ArgumentParser()
ap.add_argument("export")
ap.add_argument("--journeys", default="")
ap.add_argument("--prefix", default="")
ap.add_argument("--only", action="store_true")
a = ap.parse_args()

z = zipfile.ZipFile(a.export)
live = {os.path.basename(n)[:-5]: n for n in z.namelist()
        if re.search(r"/ido/journeys/[^/]+\.yaml$", n) and not n.endswith("/manifest.yaml")}

wanted = set() if a.only else {os.path.basename(p)[:-5] for p in glob.glob("journeys/*.yaml")}
wanted |= {j.strip() for j in a.journeys.split(",") if j.strip()}
if a.prefix:
    wanted |= {j for j in live if j.startswith(a.prefix)}

os.makedirs("journeys", exist_ok=True)
for j in sorted(wanted):
    if j not in live:
        print(f"::warning::{j}: in Git or requested, but not on the tenant (not deleted)")
        continue
    text = z.read(live[j]).decode()
    text = re.sub(r"^last_modified_date: .*\n", "", text, flags=re.M)   # changes on every save
    path = f"journeys/{j}.yaml"
    old = open(path).read() if os.path.exists(path) else None
    if old != text:
        open(path, "w").write(text)
        print(("updated " if old else "added   ") + path)
    else:
        print(f"same    {path}")
