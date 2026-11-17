# transmit-provider

Test of the unofficial Transmit Terraform provider (source: local project
`terraform-provider-transmit`, not published) on HCP Terraform. Lives on branch `transmit-provider`
only; it is not part of the CI/CD pipeline.

- HCP workspace: `transmit-provider`, VCS branch `transmit-provider`, working directory
  `transmit-provider`, trigger path `transmit-provider/**`.
- Target: dev tenant (amato-rosato-sbx-demo).
- The provider binary (linux_amd64, v0.1.0) is in
  `terraform.d/plugins/registry.terraform.io/amatorosato/transmit/0.1.0/linux_amd64/`;
  Terraform uses that folder as a local mirror, so no registry is needed.

Resources: journey `TF-HCP-Login`, app `TF HCP Demo App` with OIDC client `TF HCP Demo Web` and
role `tf-hcp-viewer`. Destroy renames the journey `DELETED-TF-HCP-Login` (the API cannot delete
journeys) and deletes the app, client and role.
