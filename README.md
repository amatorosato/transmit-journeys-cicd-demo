# Transmit journeys — CI/CD demo

Transmit journeys kept in Git and promoted between tenants by GitHub Actions, using the
Version Management API (export / validate / import). No Terraform, no extra servers.

| GitHub environment | Tenant | Role in the demo |
|---|---|---|
| `dev` | amato-rosato-sbx-demo (region `sbx`) | development: designers work here, every PR is validated here, every merge deploys here |
| `test` | telco-demo-tenant (region `us`) | test: deploy only after approval (required reviewers) |
| `prod` | Vodafone-CIAM-POC (region `eu`) | **production**: deploy only after a second approval |
| `test-readonly` | same tenant as `test`, no approval | used only by the drift check, which never changes the tenant |
| `prod-readonly` | same tenant as `prod`, no approval | used only by the drift check |

All jobs run on GitHub's runners (the three tenants have public APIs).

## Repository

```
journeys/            one YAML file per journey (Version Management export format)
sub-journeys/        (optional) sub-journeys
connections/         (optional) external connections
scripts/tsvm.sh      build / validate / import / export
scripts/guard.py     safety + structure checks (refuses empty or non-selective packages)
scripts/drift.py     compares Git with a tenant export
scripts/capture.py   copies journeys from a tenant export into journeys/ (console -> Git)
.github/workflows/   pr.yml, deploy.yml (+ _deploy.yml), drift.yml, capture.yml
```

## Pipeline

| Workflow | When | What |
|---|---|---|
| **PR check** (`pr.yml`) | every pull request | build → guard → validate on `dev`. Nothing is imported. Required check on `main`. |
| **Deploy (manual fallback)** (`deploy.yml`) | on demand only (deploys are done by HCP Terraform) | `dev`: backup export → validate → import with rollback → verify. Then **waits for approval** and repeats on `test`, then waits for a second approval and repeats on `prod`, always with the same commit. |
| **Capture from dev** (`capture.yml`) | on demand (Run workflow) | exports the dev tenant and copies into Git the journeys changed in the console (journeys already in Git, the ids you name, and every id starting with the prefix, default `CICD-`) and their **external connections** (`connections/<id>.yaml`: the ones already in Git, the ones you name, and every connection the journeys use). Opens a PR, lists the secrets (credential aliases) the connections need on the test and prod tenants, and starts its check. |
| **Drift check** (`drift.yml`) | nightly + on demand | exports the test and prod tenants and compares them with Git. **Git always wins:** when a tenant differs (edited in the console, or the latest version not applied), it opens a **restore pull request** (`restore/<stage>-tenant`, updated while open) with the diff. It only changes `terraform/restore/<stage>`: once merged, `transmit-<stage>` deploys the Git version again (Confirm & apply), the other workspaces plan no changes. |

Notes:
- Transmit's validate answers HTTP 201 even when it finds problems; the scripts read `status` in the body.
- Validate checks versions and dependencies (e.g. a missing sub-journey), not the content of each step;
  `guard.py` adds structural checks.
- Imports are always **selective**: only the journeys in the package are touched.
- The backup of each tenant is kept as a workflow artifact for 90 days.

## Terraform (HCP Terraform)

Deploys are done by HCP Terraform (organization `amato-transmit-demo`). The same code in `terraform/` runs in three workspaces, one per stage:

| Workspace | Tenant | `TS_STAGE` | `TS_REGION` |
|---|---|---|---|
| `transmit-dev` | amato-rosato-sbx-demo | dev | sbx |
| `transmit-test` | telco-demo-tenant | test | us |
| `transmit-prod` | Vodafone-CIAM-POC | production | eu |

Transmit has no Terraform provider: Terraform tracks one entry per journey and, on apply, runs `terraform/deploy.sh`, which uses the same scripts as the GitHub pipeline (backup, guard, validate, import with rollback, check that the tenant matches Git).

- **Pull request:** each workspace runs a speculative plan, reported as a check on the PR: the journeys that are new or changed on each tenant, and only the fields that change, e.g. `~ "Display Information #a57b0299 › action › title › value" = "`Signed in`" -> "`Welcome back`"` (`terraform/flatten.py` turns each journey into readable *step › field* lines; form fields are listed by name).
- **Merge to `main`:** `transmit-dev` applies automatically (Auto-apply). `transmit-test` and `transmit-prod` plan and wait: **Confirm & apply** is the approval.
- **Promotion gate:** before importing, `transmit-test` checks that amato-rosato-sbx-demo already has exactly this version, and `transmit-prod` checks telco-demo-tenant. If not, the apply is refused (*Apply transmit-dev first*), so the order dev → test → prod is enforced.
- Workspace settings: execution mode Remote, Auto-apply on `transmit-dev` and Manual apply on the others, working directory `terraform`, VCS branch `main`, trigger paths `terraform/**`, `journeys/**` and `connections/**`, automatic speculative plans on.
- Workspace variables: `TS_TENANT_ID`, `TS_REGION`, `TS_TENANT_NAME`, `TS_STAGE` as Terraform variables; `TS_CLIENT_ID`, `TS_CLIENT_SECRET` as sensitive **Environment** variables. On `transmit-test` and `transmit-prod`, the same for the previous stage with the `PREV_` prefix (`PREV_TS_TENANT_ID`, …, `PREV_TS_CLIENT_SECRET`).
- External connections in `connections/` are deployed with the journeys and shown in the plan the same way (`terraform_data.connection["<name>"]`, e.g. `config › web_request › uri › value`). Their secrets are not exported: the credential aliases must exist on every tenant.
- Removing a journey file does not delete the journey on the tenant (delete it in the console).
- `terraform/restore/<stage>` (`test`, `prod`) holds the time of the last restore request, written by the drift check's restore pull request. A new value forces the deploy again on that stage only. One file per tenant, so two restore pull requests never conflict.

## Working in the console

Designers can keep using the visual editor **on the dev tenant**:
1. Edit and test the journey in the dev console (amato-rosato-sbx-demo).
2. In GitHub: **Actions → Capture from dev → Run workflow** (optionally name new journeys).
3. Review the pull request it opens (the diff shows exactly what changed in the console), merge it.
4. The usual deploy takes it to `test` and `prod`, each after approval.

Do not edit `test` or `prod` in the console: the drift check flags it and the next deploy overwrites it.
New journeys are captured only when named or when their id starts with the prefix, so the other dev
journeys stay out of the repo. Deleting a journey is a manual step (the pipeline never deletes).

## Demo script (~20 min)

1. **Journeys are code (2 min).** Open `journeys/CICD-Demo-Login.yaml`: steps, form, texts, all readable
   and versioned. *"The journey is code, with history and review."*
2. **A change with a pull request (5 min).** Open the PR from branch `demo/change-welcome-text`
   (new form title). The PR check starts by itself and validates on `dev`; the HCP Terraform checks
   show the plan for each tenant (`~ terraform_data.journey["CICD-Demo-Login"]`). Show the diff: one line.
3. **The pipeline stops an error (4 min).** Open the PR from `demo/broken-missing-subjourney`: the journey
   calls a sub-journey that does not exist on the tenant → validate fails with `MISSING_DEPENDENCIES`,
   the check is red, merge is blocked. Optional: `demo/broken-empty-package` (all journeys deleted by
   mistake) → the guard answers `REFUSED`. *"Errors stop before production."*
4. **Merge and promotion with approval (5 min).** Merge the good PR. In HCP Terraform, the three
   workspaces plan the same commit: `transmit-dev` applies by itself (backup, import, verify) and the
   plans of `transmit-test` and `transmit-prod` show the changed lines. **Confirm & apply** on
   `transmit-test`, then on `transmit-prod`. Optional: confirm `transmit-prod` first and show the refusal
   (*Apply transmit-test first*). Show the new title in the form builder
   or with the console's *Test journey*. *"Your Terraform pipeline, your approvals, one artifact."*
5. **Drift and console edits (3 min).** Change the form title of `CICD-Demo-Login` in the form builder of
   the prod tenant, then run **Drift check** manually: **Drift on prod tenant** is red, shows the changed
   line, and opens the pull request **Restore the Git version on the prod tenant**. Merge it: in HCP,
   `transmit-prod` plans `terraform_data.deploy must be replaced`. **Confirm & apply**, and the Git
   version is back on the prod tenant.
   *"Production only changes through the pipeline: anything else is put back, with a trace in Git."*
6. **Rollback (2 min, optional).** Revert the merge commit with a PR and apply it again in the three
   workspaces.

Before the demo: run the whole flow once the day before; record the full deploy in case the runners are slow.
