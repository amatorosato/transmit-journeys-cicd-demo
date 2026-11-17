# Test of the unofficial Transmit Terraform provider on HCP Terraform (workspace transmit-provider).
# The provider binary ships in terraform.d/plugins (implied local mirror): no registry needed.
# Credentials come from the workspace Environment variables TS_TENANT_ID, TS_REGION,
# TS_CLIENT_ID and TS_CLIENT_SECRET (sensitive).
terraform {
  required_providers {
    transmit = {
      source  = "amatorosato/transmit"
      version = "0.1.0"
    }
  }
}

provider "transmit" {}

resource "transmit_journey" "login" {
  content = file("${path.module}/journeys/TF-HCP-Login.yaml")
}

resource "transmit_application" "demo" {
  name        = "TF HCP Demo App"
  description = "Managed by HCP Terraform"
}

# The API creates apps without clients: the first one becomes the default client.
resource "transmit_oidc_client" "web" {
  app_id        = transmit_application.demo.id
  name          = "TF HCP Demo Web"
  redirect_uris = ["https://localhost:3000/callback"]
  client_type   = "web"
}

resource "transmit_role" "viewer" {
  app_id      = transmit_application.demo.id
  name        = "tf-hcp-viewer"
  description = "Role managed by HCP Terraform"
  permissions = ["tf-demo:read"]
}

data "transmit_secret_aliases" "all" {}

data "transmit_tenant_entities" "all" {}

output "journey" { value = "${transmit_journey.login.name} (${transmit_journey.login.id})" }
output "app_id" { value = transmit_application.demo.id }
output "web_client_id" { value = transmit_oidc_client.web.client_id }
output "web_client_secret" {
  value     = transmit_oidc_client.web.client_secret
  sensitive = true
}
output "credential_aliases" { value = data.transmit_secret_aliases.all.credentials }
output "tenant_journey_count" { value = length(data.transmit_tenant_entities.all.journeys) }
