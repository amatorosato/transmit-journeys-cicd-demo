"""Safety and structure checks on a package before it reaches a tenant.

Transmit's validate checks versions and dependencies, not the content of a journey, and an import of a
package with no entities (or a non-selective manifest) can delete every journey on the tenant. This guard
refuses such packages and catches basic structural mistakes.
Usage: python3 scripts/guard.py <pkg.zip>
"""
import re
import sys
import zipfile

import yaml

DIRS = ("journeys", "sub-journeys", "external-connections")


def fail(msg):
    sys.exit(f"REFUSED: {msg}")


def steps_of(workflow):
    for st in workflow.get("steps") or []:
        yield st
        for link in (st.get("links") or {}).values():
            yield from steps_of({"steps": link.get("target")})
        yield from steps_of({"steps": (st.get("data") or {}).get("$inner_loop_body")})


def check_container(name, doc, workflow):
    if not isinstance(workflow, dict) or not workflow.get("steps"):
        fail(f"{name}: workflow has no steps")
    ids = set()
    for st in steps_of(workflow):
        if "$goto" in st:
            continue
        d = st.get("data") or {}
        if not d.get("id") or not d.get("type"):
            fail(f"{name}: step '{d.get('ui_name')}' without id or type")
        if d["id"] in ids:
            fail(f"{name}: duplicate step id {d['id']}")
        ids.add(d["id"])


def main(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    entities = [n for n in names if re.search(r"/ido/(%s)/[^/]+\.yaml$" % "|".join(DIRS), n)
                and not n.endswith("/manifest.yaml")]
    if not entities:
        fail("no journey, sub-journey or connection in the package (an import would empty the tenant)")
    for n in names:
        if n.endswith("/manifest.yaml") and re.search(r"/ido/(%s)/" % "|".join(DIRS), n):
            if not re.search(r"^mode:\s*selective\s*$", z.read(n).decode(), re.M):
                fail(f"{n} is not mode: selective")
    for n in entities:
        try:
            doc = yaml.safe_load(z.read(n))
        except yaml.YAMLError as e:
            fail(f"{n}: invalid YAML ({e})")
        if "/journeys/" in n:
            pid = doc.get("policy_id")
            if pid != n.rsplit("/", 1)[1][:-5]:
                fail(f"{n}: policy_id '{pid}' does not match the file name")
            if not doc.get("versions"):
                fail(f"{n}: no versions")
            for v in doc["versions"]:
                check_container(pid, doc, v.get("workflow"))
        elif "/sub-journeys/" in n:
            check_container(doc.get("name"), doc, doc.get("workflow"))
    print(f"guard OK: {len(entities)} entities, selective manifests")


if __name__ == "__main__":
    main(sys.argv[1])
