"""Compare the journeys in Git with what is live on the tenant.
Usage: python3 scripts/drift.py <tenant-export.zip>
Exit 1 if a journey in journeys/ is missing on the tenant or differs from Git.
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


def main(export_zip):
    z = zipfile.ZipFile(export_zip)
    live = {n.rsplit("/", 1)[1]: n for n in z.namelist() if "/ido/journeys/" in n and n.endswith(".yaml")}
    drift = 0
    for path in sorted(glob.glob("journeys/*.yaml")):
        fname = os.path.basename(path)
        if fname not in live:
            print(f"::error::{fname}: in Git, not on the tenant")
            drift += 1
            continue
        want = norm(yaml.safe_load(open(path)))
        have = norm(yaml.safe_load(z.read(live[fname])))
        if want == have:
            print(f"OK    {fname}: tenant matches Git")
            continue
        drift += 1
        print(f"::error::{fname}: tenant differs from Git (changed outside the pipeline?)")
        sys.stdout.writelines(l + "\n" for l in difflib.unified_diff(want, have, "git/" + fname, "tenant/" + fname,
                                                                   lineterm=""))
    sys.exit(1 if drift else 0)


if __name__ == "__main__":
    main(sys.argv[1])
