# Transmit journeys — CI/CD demo

Transmit journeys kept in Git and promoted between tenants by GitHub Actions, using the
Version Management API (export / validate / import). No Terraform, no extra servers.

| GitHub environment | Tenant | Role in the demo |
|---|---|---|
| `dev` | B2B Core Steps Test Tenant (region `dev`) | development: every PR is validated here, every merge deploys here |
| `sbx` | amato-rosato-sbx-demo (region `sbx`) | staging: deploy only after approval (required reviewers) |
| `prod` | Vodafone-CIAM-POC (region `eu`) | **production**: deploy only after a second approval |
| `sbx-readonly` | same tenant as `sbx`, no approval | used only by the drift check, which never changes the tenant |
| `prod-readonly` | same tenant as `prod`, no approval | used only by the drift check |

The DEV tenant (`api.idsec-dev.com`) only accepts the corporate network, so the `dev` jobs run on a
**self-hosted runner** (label `transmit-dev`) on a machine inside that network; the `sbx` and `prod` jobs run on GitHub's runners.

## Repository

```
journeys/            one YAML file per journey (Version Management export format)
sub-journeys/        (optional) sub-journeys
connections/         (optional) external connections
scripts/tsvm.sh      build / validate / import / export
scripts/guard.py     safety + structure checks (refuses empty or non-selective packages)
scripts/drift.py     compares Git with a tenant export
.github/workflows/   pr.yml, deploy.yml (+ _deploy.yml), drift.yml
```

## Pipeline

| Workflow | When | What |
|---|---|---|
| **PR check** (`pr.yml`) | every pull request | build → guard → validate on `dev`. Nothing is imported. Required check on `main`. |
| **Deploy** (`deploy.yml`) | merge to `main` | `dev`: backup export → validate → import with rollback → verify. Then **waits for approval** and repeats on `sbx`, then waits for a second approval and repeats on `prod`, always with the same commit. |
| **Drift check** (`drift.yml`) | nightly + on demand | exports each tenant and flags journeys that differ from Git. |

Notes:
- Transmit's validate answers HTTP 201 even when it finds problems; the scripts read `status` in the body.
- Validate checks versions and dependencies (e.g. a missing sub-journey), not the content of each step;
  `guard.py` adds structural checks.
- Imports are always **selective**: only the journeys in the package are touched.
- The backup of each tenant is kept as a workflow artifact for 90 days.

## Demo script (~20 min)

1. **Journeys are code (2 min).** Open `journeys/CICD-Demo-Login.yaml`: steps, form, texts, all readable
   and versioned. *"The journey is code, with history and review."*
2. **A change with a pull request (5 min).** Open the PR from branch `demo/change-welcome-text`
   (new form title). The PR check starts by itself and validates on `dev`. Show the diff: one line.
3. **The pipeline stops an error (4 min).** Open the PR from `demo/broken-missing-subjourney`: the journey
   calls a sub-journey that does not exist on the tenant → validate fails with `MISSING_DEPENDENCIES`,
   the check is red, merge is blocked. Optional: `demo/broken-empty-package` (all journeys deleted by
   mistake) → the guard answers `REFUSED`. *"Errors stop before production."*
4. **Merge and promotion with approval (5 min).** Merge the good PR. Deploy runs on `dev` (backup, import,
   verify), then stops on **Review deployments** for `sbx`. Approve, and the same commit reaches `sbx`;
   it stops again for `prod`: approve, and it reaches production. Show the new title in the form builder
   or with the console's *Test journey*. *"Separation of duties, audit trail, one artifact."*
5. **Drift and console edits (3 min).** Change the form title of `CICD-Demo-Login` in the form builder on
   `prod`, then run **Drift check** manually: the `prod-readonly` job is red and shows the changed line.
   *"Designers can use the visual editor; Git catches the difference."*
6. **Rollback (2 min, optional).** Revert the merge commit with a PR and promote it again, or download the
   backup artifact saved before the import.

Before the demo: run the whole flow once the day before; record the full deploy in case the runners are slow.
