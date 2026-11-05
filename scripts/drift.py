"""Compare the journeys in Git with what is live on the tenant.
Usage: python3 scripts/drift.py <tenant-export.zip>
Exit 1 if a journey in journeys/ is missing on the tenant or differs from Git.
Git always wins: when a journey differs, the drift workflow opens a restore pull request; once merged, HCP
Terraform deploys the Git version again on that tenant (after Confirm & apply).
DRIFT_REPORT (optional): markdown file with the journeys that differ and their diff, for the pull request.
Optional env: TS_STAGE (dev, test, prod: messages say "the test tenant"), GITHUB_STEP_SUMMARY (set by GitHub
Actions: a summary table is written there).
"""
import difflib
import glob
import os
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
    """Name as shown in the console (journey name, or connection name), plus the file when they differ."""
    doc = doc or {}
    name = doc.get("name") or (doc.get("data") or {}).get("name") or fname[:-5]
    return name if fname == name + ".yaml" else f"{name} ({fname})"


def error(title, text):
    """GitHub Actions annotation in a workflow, plain line elsewhere (e.g. HCP Terraform)."""
    print(f"::error title={title}::{text}" if os.environ.get("GITHUB_ACTIONS") else f"ERROR {text}")


def main(export_zip):
    stage = {"production": "prod"}.get(os.environ.get("TS_STAGE", ""), os.environ.get("TS_STAGE"))
    tenant = f"the {stage} tenant" if stage else "the tenant"
    workspace = f"transmit-{stage}" if stage else "the Terraform workspace"
    fix = f"Merge the restore pull request, then Confirm & apply in {workspace}: the Git version is put back"
    report = []
    z = zipfile.ZipFile(export_zip)
    # journeys/ <-> ido/journeys, connections/ <-> ido/external-connections
    live = {}
    for n in z.namelist():
        for git_dir, tenant_dir in (("journeys", "/ido/journeys/"), ("connections", "/ido/external-connections/")):
            if tenant_dir in n and n.endswith(".yaml") and not n.endswith("/manifest.yaml"):
                live[f"{git_dir}/{n.rsplit('/', 1)[1]}"] = n
    rows = []
    for path in sorted(glob.glob("journeys/*.yaml")) + sorted(glob.glob("connections/*.yaml")):
        fname = os.path.basename(path)
        doc = yaml.safe_load(open(path))
        name = label(doc, fname)
        short = (doc or {}).get("name") or ((doc or {}).get("data") or {}).get("name") or fname[:-5]
        if path not in live and short.startswith("DELETED-"):
            print(f"OK    {name}: soft-deleted, not on {tenant}")
            rows.append((name, "✅ deleted", ""))
            continue
        if path not in live:
            error(f"{short} is not deployed on {tenant}", f"{name} is in Git but not on {tenant}. {fix}.")
            rows.append((name, "❌ not deployed yet", fix))
            continue
        want = norm(doc)
        have = norm(yaml.safe_load(z.read(live[path])))
        if want == have:
            print(f"OK    {name}: {tenant} matches Git")
            rows.append((name, "✅ matches Git", ""))
            continue
        error(f"{short} differs on {tenant}",
              f"{name} on {tenant} differs from Git (edited in the console, or the latest version is not applied "
              f"yet). {fix}. The diff is in the log.")
        rows.append((name, "❌ differs from Git", fix))
        diff = list(difflib.unified_diff(want, have, "git/" + fname, "tenant/" + fname, lineterm=""))
        report.append(f"#### {name}\n\n```diff\n" + "\n".join(diff[:200]) +
                      ("\n… (diff truncated)" if len(diff) > 200 else "") + "\n```\n")
        print(f"--- what changed on {tenant} (- Git, + {tenant}) ---")
        sys.stdout.writelines(l + "\n" for l in difflib.unified_diff(want, have, "git/" + fname, "tenant/" + fname,
                                                                   lineterm=""))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### Journeys on {tenant} compared with Git\n\n| Journey | Status | What to do |\n|---|---|---|\n")
            f.writelines(f"| {n} | {st} | {fx} |\n" for n, st, fx in rows)
    if os.environ.get("DRIFT_REPORT"):
        missing = [n for n, st, _ in rows if st.startswith("❌ not deployed")]
        with open(os.environ["DRIFT_REPORT"], "w") as f:
            f.write("".join(report) + "".join(f"#### {n}\n\nIn Git, not on {tenant}.\n" for n in missing))
    sys.exit(0 if all(st.startswith("✅") for _, st, _ in rows) else 1)


if __name__ == "__main__":
    main(sys.argv[1])
