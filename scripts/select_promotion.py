"""Files to promote to prod for the journeys asked by name (run on main).
Usage: python3 scripts/select_promotion.py "CICD-Demo-Login, JourneyTest"
A journey can be named as in the console (a soft-deleted one also without DELETED-) or by file id. Prints the files
to promote, one per line: the journeys and the external connections they use. Exits 2 with the list of journeys if
a name is unknown.
"""
import glob
import os
import re
import sys

import yaml

wanted = [x.strip() for x in sys.argv[1].split(",") if x.strip()]
journeys = {}
for p in sorted(glob.glob("journeys/*.yaml")):
    name = (yaml.safe_load(open(p)) or {}).get("name") or ""
    for key in {name, name.removeprefix("DELETED-"), os.path.basename(p)[:-5]}:
        journeys.setdefault(key.lower(), []).append(p)
unknown = [w for w in wanted if w.lower() not in journeys]
if unknown:
    names = sorted({(yaml.safe_load(open(p)) or {}).get("name") or p for p in glob.glob("journeys/*.yaml")})
    sys.exit(f"::error title=Unknown journey::{', '.join(unknown)}. Journeys in main: {', '.join(names)}")

files = sorted({p for w in wanted for p in journeys[w.lower()]})
conns = {}
for p in glob.glob("connections/*.yaml"):
    conns[((yaml.safe_load(open(p)) or {}).get("data") or {}).get("name")] = p
used = set()
for p in files:
    text = open(p).read()
    used |= {conns[f] for f in re.findall(r"function:\s*['\"]?([\w.\-]+)", text) if f in conns}
    used |= {c for c in conns.values() if os.path.basename(c)[:-5] in text}
print("\n".join(files + sorted(used)))
