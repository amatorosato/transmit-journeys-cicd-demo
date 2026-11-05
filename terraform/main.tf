# Deploys the journeys in journeys/ to one Transmit tenant. The same code runs in three HCP Terraform
# workspaces, one per stage: transmit-dev (amato-rosato-sbx-demo), transmit-test (telco-demo-tenant),
# transmit-prod (Vodafone-CIAM-POC). Transmit has no Terraform provider, so Terraform tracks the journeys
# and calls the same scripts as the GitHub pipeline (backup, guard, validate, import, check).
#
# The plan shows which journeys change. "Confirm & apply" in HCP Terraform is the approval.
terraform {
  required_version = ">= 1.5"
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
  journeys_dir = "${path.module}/../journeys"
  # journey name (as in the console) => file and content; the plan shows the changed lines
  journeys = {
    for f in fileset(local.journeys_dir, "*.yaml") :
    yamldecode(file("${local.journeys_dir}/${f}")).name => {
      file    = "journeys/${f}"
      content = file("${local.journeys_dir}/${f}")
    }
  }
  versions = { for name, j in local.journeys : name => sha256(j.content) }
}

# One entry per journey: the plan lists the journeys that are new or changed, with the changed lines.
# Removing a file only drops it from Terraform: the journey stays on the tenant (delete it in the console).
resource "terraform_data" "journey" {
  for_each = local.journeys
  input    = each.value
}

# The deploy itself: runs again whenever any journey (or the target tenant) changes.
resource "terraform_data" "deploy" {
  triggers_replace = [var.TS_TENANT_ID, local.versions]

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

  depends_on = [terraform_data.journey]
}

output "tenant" {
  value = "${replace(var.TS_STAGE, "production", "prod")} tenant"
}

output "journeys" {
  value = { for name, j in local.journeys : name => j.file }
}
