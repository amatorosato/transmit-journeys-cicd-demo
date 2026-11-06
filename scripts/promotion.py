"""What a promotion to prod changes: compares the prod branch with the version being promoted.
Usage: python3 scripts/promotion.py <prod-ref> <summary.md>   (run on the commit being promoted)
Prints the names that change (for the pull request title); writes a markdown table to <summary.md>.
Exit 3 if nothing changes in production.
"""
import difflib
import subprocess
import sys

import yaml

prod_ref, out = sys.argv[1:]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def name_of(text, path):
    d = yaml.safe_load(text) or {}
    return d.get("name") or (d.get("data") or {}).get("name") or path.rsplit("/", 1)[-1][:-5]


rows, names = [], []
for line in git("diff", "--name-status", f"{prod_ref}..HEAD", "--", "journeys", "connections").splitlines():
    status, path = line.split("\t")[0], line.split("\t")[-1]
    kind = "Journey" if path.startswith("journeys/") else "External connection"
    new = git("show", f"HEAD:{path}") if status != "D" else ""
    old = git("show", f"{prod_ref}:{path}") if status != "A" else ""
    name_new = name_of(new, path) if new else ""
    name_old = name_of(old, path) if old else ""
    if status == "A":
        if name_new.startswith("DELETED-"):
            continue                      # deleted before it ever reached production
        rows.append(("✨ New", kind, name_new, f"`{path}`"))
    elif status == "D":
        rows.append(("➖ Removed from Git", kind, name_old, "stays on the prod tenant (delete it in the console)"))
    elif name_new.startswith("DELETED-") and not name_old.startswith("DELETED-"):
        rows.append(("🗑️ Deleted", kind, name_old, f"renamed `{name_new}` on the prod tenant"))
    else:
        diff = [l for l in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
                if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        n = len([l for l in diff if l.startswith("+")]) or len(diff)
        rows.append(("✏️ Changed", kind, name_new, f"{n} line{'s' if n != 1 else ''} changed"))
    names.append(rows[-1][2])

with open(out, "w") as f:
    if rows:
        f.write(f"**{len(rows)} change{'s' if len(rows) != 1 else ''} for the prod tenant:**\n\n"
                "| | Type | Name | Details |\n|---|---|---|---|\n")
        f.writelines(f"| {s} | {k} | {n} | {d} |\n" for s, k, n, d in rows)
    else:
        f.write("**Nothing to deploy:** the prod tenant already runs this version.\n")
print(", ".join(names))
sys.exit(0 if rows else 3)
