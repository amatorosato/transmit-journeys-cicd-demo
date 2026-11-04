"""Compare the journeys in Git with what is live on the tenant.
Usage: python3 scripts/drift.py <tenant-export.zip>
Exit 1 if a journey in journeys/ is missing on the tenant or differs from Git.
Optional env: TS_TENANT_NAME (used in the messages), PENDING_DEPLOY (URL of a deploy waiting for
approval), GITHUB_STEP_SUMMARY (set by GitHub Actions: a summary table is written there).
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
    """Journey name as shown in the console, plus the file when the name is not the file name."""
    name = (doc or {}).get("name") or fname[:-5]
    return name if fname == name + ".yaml" else f"{name} ({fname})"


def main(export_zip):
    tenant = os.environ.get("TS_TENANT_NAME") or "the tenant"
    pending = os.environ.get("PENDING_DEPLOY")
    z = zipfile.ZipFile(export_zip)
    live = {n.rsplit("/", 1)[1]: n for n in z.namelist() if "/ido/journeys/" in n and n.endswith(".yaml")}
    rows = []
    for path in sorted(glob.glob("journeys/*.yaml")):
        fname = os.path.basename(path)
        doc = yaml.safe_load(open(path))
        name = label(doc, fname)
        short = (doc or {}).get("name") or fname[:-5]
        if fname not in live:
            if pending:
                fix = f"A deploy is waiting for approval: approve it to bring the journey here ({pending})"
            else:
                fix = "Run the Deploy workflow to bring the journey here"
            print(f"::error title={short} is not deployed on {tenant}::{name} is in Git but not on {tenant}. {fix}.")
            rows.append((name, "❌ not deployed yet", fix))
            continue
        want = norm(doc)
        have = norm(yaml.safe_load(z.read(live[fname])))
        if want == have:
            print(f"OK    {name}: {tenant} matches Git")
            rows.append((name, "✅ matches Git", ""))
            continue
        fix = "Re-run Deploy to put the Git version back, or bring the change into Git with a pull request"
        print(f"::error title={short} was changed on {tenant}::{name} on {tenant} differs from Git "
              f"(edited in the console, outside the pipeline). {fix}. The diff is in the log.")
        rows.append((name, "❌ changed outside Git", fix))
        print(f"--- what changed on {tenant} (- Git, + {tenant}) ---")
        sys.stdout.writelines(l + "\n" for l in difflib.unified_diff(want, have, "git/" + fname, "tenant/" + fname,
                                                                   lineterm=""))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### Journeys on {tenant} compared with Git\n\n| Journey | Status | What to do |\n|---|---|---|\n")
            f.writelines(f"| {n} | {st} | {fx} |\n" for n, st, fx in rows)
    sys.exit(1 if any(st.startswith("❌") for _, st, _ in rows) else 0)


if __name__ == "__main__":
    main(sys.argv[1])
