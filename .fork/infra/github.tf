locals {
  ci_secrets = {
    R2_ACCESS_KEY_ID     = module.ci_token.access_key_id
    R2_SECRET_ACCESS_KEY = module.ci_token.secret_access_key
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

  # Retries cover the short window where GitHub hasn't registered the
  # workflows yet after Actions is enabled.
  provisioner "local-exec" {
    command = join(" && ", [
      for wf in self.input :
      "for i in 1 2 3 4 5; do gh workflow disable ${wf} --repo ${var.github_owner}/${var.github_repository} && break; [ $i = 5 ] && exit 1; sleep 5; done"
    ])
  }

  depends_on = [github_actions_repository_permissions.repo]
}
