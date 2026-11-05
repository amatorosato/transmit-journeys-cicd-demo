"""Compare the journeys in Git with what is live on the tenant.
Usage: python3 scripts/drift.py <tenant-export.zip>
Exit 1 if a journey in journeys/ is missing on the tenant or differs from Git.
A journey that differs is either an older version from Git (not applied yet) or an edit made in the console.
DEPLOYED_VERSIONS (optional): JSON {"journeys/<file>": sha256} of what HCP Terraform last applied on this tenant.
With it: Git != applied -> not applied yet; Git == applied but tenant different -> edited in the console.
Without it, a tenant version equal to an earlier Git version is reported as "older version" (ambiguous).
With DRIFT_EDITED set, the console edits are written there (one "file<TAB>name" per line) for a pull request.
Optional env: TS_STAGE (dev, test, prod: messages say "the test tenant"), GITHUB_STEP_SUMMARY (set by GitHub
Actions: a summary table is written there).
"""
import difflib
import glob
import hashlib
import json
import os
import subprocess
import sys
import zipfile

import yaml


IGNORED = ("last_modified_date",)   # added by the tenant on export


class _Dumper(yaml.SafeDumper):
    pass


# multi-line strings (e.g. a form schema) as blocks, so the diff shows only the changed lines
_Dumper.add_representer(str, lambda d, v: d.represent_scalar(
    "tag:yaml.org,2002:str", v, style="|" if "\n" in v else None))


def norm(doc):
    doc = {k: v for k, v in doc.items() if k not in IGNORED}
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=True, width=1000, allow_unicode=True).splitlines()


def label(doc, fname):
    """Journey name as shown in the console, plus the file when the name is not the file name."""
    name = (doc or {}).get("name") or fname[:-5]
    return name if fname == name + ".yaml" else f"{name} ({fname})"


def in_git_history(path, have):
    """True if the tenant's version equals an earlier version of the file in Git (needs full history)."""
    try:
        commits = subprocess.run(["git", "log", "--format=%H", "--", path],
                                 capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return False
    for c in commits[1:]:
        old = subprocess.run(["git", "show", f"{c}:{path}"], capture_output=True, text=True)
        if old.returncode == 0 and norm(yaml.safe_load(old.stdout) or {}) == have:
            return True
    return False


def error(title, text):
    """GitHub Actions annotation in a workflow, plain line elsewhere (e.g. HCP Terraform)."""
    print(f"::error title={title}::{text}" if os.environ.get("GITHUB_ACTIONS") else f"ERROR {text}")


def main(export_zip):
    stage = {"production": "prod"}.get(os.environ.get("TS_STAGE", ""), os.environ.get("TS_STAGE"))
    tenant = f"the {stage} tenant" if stage else "the tenant"
    workspace = f"transmit-{stage}" if stage else "the Terraform workspace"
    edited = []
    applied = None
    if os.environ.get("DEPLOYED_VERSIONS") and os.path.exists(os.environ["DEPLOYED_VERSIONS"]):
        applied = json.load(open(os.environ["DEPLOYED_VERSIONS"]))
    z = zipfile.ZipFile(export_zip)
    live = {n.rsplit("/", 1)[1]: n for n in z.namelist() if "/ido/journeys/" in n and n.endswith(".yaml")}
    rows = []
    for path in sorted(glob.glob("journeys/*.yaml")):
        fname = os.path.basename(path)
        doc = yaml.safe_load(open(path))
        name = label(doc, fname)
        short = (doc or {}).get("name") or fname[:-5]
        if fname not in live:
            fix = f"Confirm & apply the waiting run in {workspace} (or start a new run there)"
            error(f"{short} is not deployed on {tenant}", f"{name} is in Git but not on {tenant}. {fix}.")
            rows.append((name, "❌ not deployed yet", fix))
            continue
        want = norm(doc)
        have = norm(yaml.safe_load(z.read(live[fname])))
        if want == have:
            print(f"OK    {name}: {tenant} matches Git")
            rows.append((name, "✅ matches Git", ""))
            continue
        pending_fix = f"Confirm & apply the waiting run in {workspace} (or start a new run there)"
        if applied is not None:
            git_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
            not_applied = applied.get(path) != git_sha
        else:
            not_applied = None if in_git_history(path, have) else False
        if not_applied:
            error(f"{short}: not applied yet on {tenant}",
                  f"{name}: the latest version in Git is not applied on {tenant} yet. {pending_fix}.")
            rows.append((name, "⏳ not applied yet", pending_fix))
        elif not_applied is None:
            fix = (f"{pending_fix}; if nothing is waiting there, a change was undone in the console: set "
                   "TF_API_TOKEN so the drift check can tell the two cases apart")
            error(f"{short}: older version on {tenant}",
                  f"{name} on {tenant} equals an older version in Git: either the latest one is not applied yet, "
                  f"or a change was undone in the console. {fix}.")
            rows.append((name, "⏳ older version", fix))
        else:
            fix = ("A pull request with this version is opened: merge it to keep the change, or close it and "
                   f"start a new run in {workspace} to put the Git version back")
            error(f"{short} was edited on {tenant}",
                  f"{name} was edited in the console of {tenant}: it differs from the version applied by the pipeline. {fix}. "
                  "The diff is in the log.")
            rows.append((name, "❌ edited in the console", fix))
            edited.append((fname, short))
        print(f"--- what changed on {tenant} (- Git, + {tenant}) ---")
        sys.stdout.writelines(l + "\n" for l in difflib.unified_diff(want, have, "git/" + fname, "tenant/" + fname,
                                                                   lineterm=""))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### Journeys on {tenant} compared with Git\n\n| Journey | Status | What to do |\n|---|---|---|\n")
            f.writelines(f"| {n} | {st} | {fx} |\n" for n, st, fx in rows)
    if os.environ.get("DRIFT_EDITED"):
        with open(os.environ["DRIFT_EDITED"], "w") as f:
            f.writelines(f"{fn}\t{n}\n" for fn, n in edited)
    sys.exit(0 if all(st.startswith("✅") for _, st, _ in rows) else 1)


if __name__ == "__main__":
    main(sys.argv[1])
