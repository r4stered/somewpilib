locals {
  ci_secrets = {
    R2_ACCESS_KEY_ID     = cloudflare_account_token.ci.id
    R2_SECRET_ACCESS_KEY = sha256(cloudflare_account_token.ci.value)
    ANTHROPIC_API_KEY    = var.anthropic_api_key
  }

  ci_variables = {
    R2_BUCKET   = cloudflare_r2_bucket.ci.name
    R2_ENDPOINT = local.r2_endpoint
  }

  # Upstream's scheduled workflows stay on main until the birth merge deletes
  # them, and schedules run from the default branch.
  upstream_scheduled_workflows = [
    "artifactory-nightly-cleanup.yml",
    "sentinel-build.yml",
  ]
}

resource "github_actions_secret" "ci" {
  for_each = nonsensitive(toset(keys(local.ci_secrets)))

  repository  = var.github_repository
  secret_name = each.key
  value       = local.ci_secrets[each.key]
}

resource "github_actions_variable" "ci" {
  for_each = local.ci_variables

  repository    = var.github_repository
  variable_name = each.key
  value         = each.value
}

resource "github_actions_repository_permissions" "repo" {
  repository      = var.github_repository
  enabled         = true
  allowed_actions = "all"
}

# The GitHub provider cannot disable a workflow, so this shells out to gh
# right after Actions is turned on, before any schedule can fire.
resource "terraform_data" "disable_upstream_schedules" {
  input = local.upstream_scheduled_workflows

  provisioner "local-exec" {
    command = join(" && ", [
      for wf in local.upstream_scheduled_workflows :
      "gh workflow disable ${wf} --repo ${var.github_owner}/${var.github_repository}"
    ])
  }

  depends_on = [github_actions_repository_permissions.repo]
}
