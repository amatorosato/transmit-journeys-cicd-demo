"""Promotion status: compare the tenants with each other (dev -> test, test -> prod), for the journeys and external
connections in Git (main and prod). Informational only: it never fails and never opens a pull request (the drift
check compares each tenant with Git and restores it).
  python3 scripts/status.py collect <tenant-export.zip> <out-dir>
      keep only the files that are in Git (journeys/, connections/ on main or prod), as journeys/<f>, connections/<f>
  python3 scripts/status.py report <dev-dir> <test-dir> <prod-dir> [summary.md]
      table "dev tenant -> test tenant", "test tenant -> prod tenant" with what differs, in words, and the next step
      (from Git: main is what dev and test should run, the prod branch what prod should run). Run on main, with the
      prod branch fetched (origin/prod).
"""
import glob
import os
import re
import subprocess
import sys
import zipfile

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from describe import explain, headline  # noqa: E402
from drift import norm  # noqa: E402

DIRS = (("journeys", "/ido/journeys/", "Journey"), ("connections", "/ido/external-connections/", "External connection"))
DEL = "DELETED-"


def git_files(ref):
    """{path: text} of journeys/ and connections/ on a branch ("" = the working tree)."""
    if not ref:
        return {p: open(p).read() for d, _, _ in DIRS for p in sorted(glob.glob(f"{d}/*.yaml"))}
    out = subprocess.run(["git", "ls-tree", "--name-only", ref, "journeys/", "connections/"],
                         capture_output=True, text=True).stdout.split()
    return {p: subprocess.run(["git", "show", f"{ref}:{p}"], capture_output=True, text=True).stdout
            for p in out if p.endswith(".yaml")}


def collect(export, out):
    wanted = set(git_files("")) | set(git_files("origin/prod"))
    z = zipfile.ZipFile(export)
    for n in z.namelist():
        for d, tenant_dir, _ in DIRS:
            if tenant_dir in n and n.endswith(".yaml") and not n.endswith("/manifest.yaml"):
                path = f"{d}/{n.rsplit('/', 1)[1]}"
                if path in wanted:
                    os.makedirs(os.path.join(out, d), exist_ok=True)
                    open(os.path.join(out, path), "w").write(z.read(n).decode())
    print(f"kept {sum(len(f) for _, _, f in os.walk(out))} files from {export}")


def load(text):
    return yaml.safe_load(text) if text else None


def name_of(doc):
    doc = doc or {}
    return doc.get("name") or (doc.get("data") or {}).get("name") or ""


def effective(text, git_text):
    """What the tenant runs. A soft-deleted journey (DELETED- in Git) that is not on the tenant counts as deleted."""
    if text is None and git_text and name_of(load(git_text)).startswith(DEL):
        return git_text
    return text


def same(a, b):
    if a is None or b is None:
        return a is b
    return norm(load(a)) == norm(load(b))


def compare(kind, ahead, behind, a_name, b_name):
    """(short status, detail lines) for 'ahead' (e.g. dev) against 'behind' (e.g. test)."""
    if same(ahead, behind):
        return "✅ same", []
    if behind is None:
        return f"➕ new, not on the {b_name} tenant", []
    if ahead is None:
        return f"❔ on the {b_name} tenant, not on the {a_name} tenant", []
    na, nb = name_of(load(ahead)), name_of(load(behind))
    if na.startswith(DEL) and not nb.startswith(DEL):
        return f"🗑️ deleted on the {a_name} tenant, still active on the {b_name} tenant", []
    if nb.startswith(DEL) and not na.startswith(DEL):
        return f"♻️ active on the {a_name} tenant, deleted on the {b_name} tenant", []
    try:
        lines = explain(kind, behind, ahead)
        return f"✏️ {headline(lines)}", lines
    except Exception:
        return "✏️ differs", []


def report(dev_dir, test_dir, prod_dir, summary):
    main, prod = git_files(""), git_files("origin/prod")

    def tenant(d, p):
        f = os.path.join(d, p)
        # last_modified_date is added by the tenant on export (the drift check ignores it too)
        return re.sub(r"^last_modified_date: .*\n", "", open(f).read(), flags=re.M) if os.path.exists(f) else None

    rows, details, todo = [], [], {"test": 0, "prod": 0}
    for p in sorted(set(main) | set(prod)):
        kind = next(k for d, _, k in DIRS if p.startswith(d + "/"))
        gm, gp = main.get(p), prod.get(p)
        dev = effective(tenant(dev_dir, p), gm)
        test = effective(tenant(test_dir, p), gm)
        prd = effective(tenant(prod_dir, p), gp)
        name = name_of(load(gm or gp)) or p
        if name.startswith(DEL) and all(t is None or name_of(load(t)).startswith(DEL) for t in (dev, test, prd)) \
                and same(dev, test) and same(test, prd):
            continue   # deleted everywhere: not worth listing
        s1, l1 = compare(kind, dev, test, "dev", "test")
        s2, l2 = compare(kind, test, prd, "test", "prod")
        # next step, from Git: main is what dev and test should run, the prod branch what prod should run
        steps = []
        if not same(dev, gm):
            steps.append("changed in the dev tenant console: **Capture from dev**")
        elif not same(test, gm):
            steps.append("**Confirm & apply** on `transmit-test` (or, if edited there, see **Drift check**)")
            todo["test"] += 1
        elif not same(prd, gp):
            steps.append("**Confirm & apply** on `transmit-prod` (or, if edited there, see **Drift check**)")
        elif not same(test, prd):
            steps.append("**Request prod deploy**")
            todo["prod"] += 1
        rows.append((name, kind, s1, s2, "; then ".join(steps) or "—"))
        for pair, lines in (("dev tenant → test tenant", l1), ("test tenant → prod tenant", l2)):
            if lines:
                details.append(f"**{name}**, {pair}:\n\n" + "".join(f"- {l}\n" for l in lines))

    md = ["### Promotion status: what each tenant has that the next one does not yet\n",
          "Informational: the tenants are compared with each other (the **Drift check** compares each one with Git).\n",
          "| | Type | dev tenant → test tenant | test tenant → prod tenant | Next step |",
          "|---|---|---|---|---|"]
    md += [f"| {n} | {k} | {a} | {b} | {s} |" for n, k, a, b, s in rows]
    if details:
        md += ["", "#### What differs", ""] + details
    text = "\n".join(md) + "\n"
    print(text)
    if summary:
        open(summary, "a").write(text)
    parts = [f"{todo['test']} to apply on the test tenant" if todo["test"] else "",
             f"{todo['prod']} to promote to the prod tenant" if todo["prod"] else ""]
    msg = ", ".join(x for x in parts if x) or "nothing waiting for promotion"
    print(f"::notice title=Promotion status::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"STATUS {msg}")


if __name__ == "__main__":
    if sys.argv[1] == "collect":
        collect(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "report":
        report(*sys.argv[2:5], sys.argv[5] if len(sys.argv) > 5 else os.environ.get("GITHUB_STEP_SUMMARY"))
    else:
        sys.exit(__doc__)
