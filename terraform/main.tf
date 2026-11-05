# Deploys the journeys in journeys/ to one Transmit tenant. The same code runs in three HCP Terraform
# workspaces, one per stage: transmit-dev (amato-rosato-sbx-demo), transmit-test (telco-demo-tenant),
# transmit-prod (Vodafone-CIAM-POC). Transmit has no Terraform provider, so Terraform tracks the journeys
# and calls the same scripts as the GitHub pipeline (backup, guard, validate, import, check).
#
# The plan shows which journeys change. "Confirm & apply" in HCP Terraform is the approval.
terraform {
  required_version = ">= 1.5"
  required_providers {
    external = { source = "hashicorp/external", version = "~> 2.3" }
  }
}

# Non-secret settings: workspace "Terraform variables".
# The credentials TS_CLIENT_ID / TS_CLIENT_SECRET are workspace "Environment variables" (sensitive),
# so they reach the scripts directly and never pass through the Terraform configuration.
variable "TS_TENANT_ID" {
  type        = string
  description = "Transmit tenant ID"
}

variable "TS_REGION" {
  type        = string
  description = "Transmit region: sbx, us, eu, ca or au"
}

variable "TS_TENANT_NAME" {
  type        = string
  description = "Tenant name, used in the messages"
}

variable "TS_STAGE" {
  type        = string
  description = "Stage of this workspace: dev, test or prod"
  validation {
    condition     = contains(["dev", "test", "prod", "production"], var.TS_STAGE)
    error_message = "TS_STAGE must be dev, test or prod."
  }
}

# Promotion gate (test and production only): the tenant of the previous stage must already have
# exactly this version, otherwise the apply is refused. Its credentials PREV_TS_CLIENT_ID /
# PREV_TS_CLIENT_SECRET are workspace Environment variables (sensitive), like the main ones.
variable "PREV_TS_TENANT_ID" {
  type        = string
  default     = ""
  description = "Tenant ID of the previous stage (empty on dev)"
}

variable "PREV_TS_REGION" {
  type        = string
  default     = ""
  description = "Region of the previous stage's tenant"
}

variable "PREV_TS_TENANT_NAME" {
  type        = string
  default     = ""
  description = "Name of the previous stage's tenant"
}

variable "PREV_TS_STAGE" {
  type        = string
  default     = ""
  description = "Previous stage: dev for test, test for prod"
}

locals {
  journeys_dir   = "${path.module}/../journeys"
  journey_files  = fileset(local.journeys_dir, "*.yaml")
  journey_names  = { for f in local.journey_files : f => yamldecode(file("${local.journeys_dir}/${f}")).name }
  active_names   = [for f, n in local.journey_names : n if !startswith(n, "DELETED-")]
  # key = name as in the console. A soft-deleted journey (DELETED-<name>) is keyed without the prefix, so its plan shows
  # the rename instead of destroy + create, unless another journey already has that name.
  journey_key = {
    for f, n in local.journey_names : f =>
    startswith(n, "DELETED-") && !contains(local.active_names, trimprefix(n, "DELETED-")) ? trimprefix(n, "DELETED-") : n
  }
  journey_key_files = { for f, k in local.journey_key : k => f... }
  # journey name => file and content; two journeys with the same name get their file name added to stay unique
  journeys = {
    for f, k in local.journey_key :
    (length(local.journey_key_files[k]) > 1 ? "${k} (${trimsuffix(f, ".yaml")})" : k) => {
      file    = "journeys/${f}"
      content = file("${local.journeys_dir}/${f}")
    }
  }
  versions = { for name, j in local.journeys : name => sha256(j.content) }

  # external connections (connections/<provider_id>.yaml, from Capture from dev): connection name => file
  connections_dir = "${path.module}/../connections"
  connections = {
    for f in fileset(local.connections_dir, "*.yaml") :
    yamldecode(file("${local.connections_dir}/${f}")).data.name => {
      file    = "connections/${f}"
      content = file("${local.connections_dir}/${f}")
    }
  }
  connection_versions = { for name, c in local.connections : name => sha256(c.content) }

  # Restore requests written by the drift check through a pull request: terraform/restore/<stage>
  # holds the time of the last request (one file per tenant, so two restore pull requests never conflict).
  # A new value for this stage forces the deploy again, which puts the Git version back on the tenant.
  stage        = replace(var.TS_STAGE, "production", "prod")
  restore_file = "${path.module}/restore/${local.stage}"
  restore      = fileexists(local.restore_file) ? trimspace(file(local.restore_file)) : ""
}

# Each journey as readable "step › field = value" lines (terraform/flatten.py), so the plan shows only the
# fields that change, e.g. ~ "Display Information #a57b0299 › action › title" = "`Signed in`" -> "`Welcome back`"
data "external" "journey_fields" {
  for_each = local.journeys
  program  = ["python3", "${path.module}/flatten.py"]
  query    = { journey = jsonencode(yamldecode(each.value.content)) }
}

# The same for external connections: "config › web_request › uri › value = …"
data "external" "connection_fields" {
  for_each = local.connections
  program  = ["python3", "${path.module}/flatten.py"]
  query    = { connection = jsonencode(yamldecode(each.value.content)) }
}

resource "terraform_data" "connection" {
  for_each = local.connections
  triggers_replace = {
    file   = each.value.file
    fields = data.external.connection_fields[each.key].result
  }
}

# One entry per journey: the plan lists the journeys that are new or changed, and the fields that change.
# Removing a file only drops it from Terraform: the journey stays on the tenant (delete it in the console).
resource "terraform_data" "journey" {
  for_each = local.journeys
  triggers_replace = {
    file   = each.value.file
    fields = data.external.journey_fields[each.key].result
  }
}

# The deploy itself: runs again whenever any journey (or the target tenant) changes.
resource "terraform_data" "deploy" {
  # without a restore request the triggers stay as they were, so adding restore.json changes nothing
  # connections and restore requests are added only when present, so the triggers of a tenant without them
  # stay exactly as before
  triggers_replace = concat(
    [var.TS_TENANT_ID, local.versions],
    [for c in [local.connection_versions] : c if length(c) > 0],
    [for r in [local.restore] : r if r != ""],
  )

  lifecycle {
    precondition {
      condition     = var.TS_STAGE == "dev" || var.PREV_TS_TENANT_ID != ""
      error_message = "The ${var.TS_STAGE} workspace needs the promotion gate: set PREV_TS_TENANT_ID, PREV_TS_REGION, PREV_TS_TENANT_NAME, PREV_TS_STAGE (Terraform variables) and PREV_TS_CLIENT_ID, PREV_TS_CLIENT_SECRET (Environment variables)."
    }
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "bash terraform/deploy.sh"
    environment = {
      TS_TENANT_ID   = var.TS_TENANT_ID
      TS_REGION      = var.TS_REGION
      TS_TENANT_NAME = var.TS_TENANT_NAME
      TS_STAGE       = var.TS_STAGE
      PREV_TS_TENANT_ID   = var.PREV_TS_TENANT_ID
      PREV_TS_REGION      = var.PREV_TS_REGION
      PREV_TS_TENANT_NAME = var.PREV_TS_TENANT_NAME
      PREV_TS_STAGE       = var.PREV_TS_STAGE
    }
  }

  depends_on = [terraform_data.journey, terraform_data.connection]
}

output "tenant" {
  value = "${replace(var.TS_STAGE, "production", "prod")} tenant"
}

output "journeys" {
  value = { for name, j in local.journeys : name => j.file }
}
