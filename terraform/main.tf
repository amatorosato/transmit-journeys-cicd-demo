# Deploys the journeys in journeys/ to one Transmit tenant (workspace transmit-cicd-demo:
# amato-rosato-sbx-demo). Transmit has no Terraform provider, so Terraform tracks the journeys
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

locals {
  journeys_dir = "${path.module}/../journeys"
  # journey name (as in the console) => file and content hash
  journeys = {
    for f in fileset(local.journeys_dir, "*.yaml") :
    yamldecode(file("${local.journeys_dir}/${f}")).name => {
      file   = "journeys/${f}"
      sha256 = filesha256("${local.journeys_dir}/${f}")
    }
  }
}

# One entry per journey: the plan lists exactly which journeys are new or changed.
# Removing a file only drops it from Terraform: the journey stays on the tenant (delete it in the console).
resource "terraform_data" "journey" {
  for_each = local.journeys
  input    = each.value
}

# The deploy itself: runs again whenever any journey (or the target tenant) changes.
resource "terraform_data" "deploy" {
  triggers_replace = [var.TS_TENANT_ID, local.journeys]

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "bash terraform/deploy.sh"
    environment = {
      TS_TENANT_ID   = var.TS_TENANT_ID
      TS_REGION      = var.TS_REGION
      TS_TENANT_NAME = var.TS_TENANT_NAME
      TS_STAGE       = "dev"
    }
  }

  depends_on = [terraform_data.journey]
}

output "tenant" {
  value = var.TS_TENANT_NAME
}

output "journeys" {
  value = { for name, j in local.journeys : name => j.file }
}
