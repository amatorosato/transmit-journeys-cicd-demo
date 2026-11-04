# Step 0: check what the HCP Terraform workers have before we rely on it.
# Runs during "plan" (data source), so it changes nothing on any tenant.
terraform {
  required_providers {
    external = { source = "hashicorp/external", version = "~> 2.3" }
  }
}

data "external" "probe" {
  program = ["bash", "-c", <<-EOT
    has() { command -v "$1" >/dev/null 2>&1 && echo yes || echo no; }
    pyyaml=$(python3 -c 'import yaml' >/dev/null 2>&1 && echo yes || echo no)
    pyver=$(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo none)
    sbx=$(curl -s -o /dev/null -m 10 -w '%%{http_code}' https://api.sbx.transmitsecurity.io/ 2>/dev/null || echo fail)
    printf '{"curl":"%s","python3":"%s","python_version":"%s","pyyaml":"%s","pip":"%s","zip":"%s","unzip":"%s","reach_sbx_api":"%s"}' \
      "$(has curl)" "$(has python3)" "$pyver" "$pyyaml" "$(has pip3)" "$(has zip)" "$(has unzip)" "$sbx"
  EOT
  ]
}

output "worker_tools" {
  value = data.external.probe.result
}
