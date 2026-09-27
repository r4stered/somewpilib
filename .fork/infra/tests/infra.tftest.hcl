# Plan-only checks against mocked providers. Run with `tofu test` from
# .fork/infra; no credentials or network access are needed.

mock_provider "cloudflare" {
  mock_data "cloudflare_account_api_token_permission_groups_list" {
    defaults = {
      result = [
        { id = "pg-item-read", name = "Workers R2 Storage Bucket Item Read", scopes = ["com.cloudflare.edge.r2.bucket"] },
        { id = "pg-item-write", name = "Workers R2 Storage Bucket Item Write", scopes = ["com.cloudflare.edge.r2.bucket"] },
        { id = "pg-other", name = "Workers R2 Storage Write", scopes = ["com.cloudflare.api.account"] },
      ]
    }
  }
}

mock_provider "github" {}

variables {
  cloudflare_account_id = "0123456789abcdef0123456789abcdef"
  anthropic_api_key     = "sk-ant-test"
  state_passphrase      = "a-test-passphrase-that-is-long"
}

run "bucket_has_30_day_expiry_on_both_cache_prefixes" {
  command = plan

  assert {
    condition     = cloudflare_r2_bucket.ci.name == "somewpilib-ci"
    error_message = "CI bucket name changed; workflows read it from the R2_BUCKET variable."
  }

  assert {
    condition = toset([
      for r in cloudflare_r2_bucket_lifecycle.ci.rules : r.conditions.prefix
      if r.enabled && r.delete_objects_transition != null
      && r.delete_objects_transition.condition.max_age == 30 * 24 * 60 * 60
    ]) == toset(["sccache/", "deps/"])
    error_message = "sccache/ and deps/ must each expire objects after 30 days."
  }

  assert {
    condition = anytrue([
      for r in cloudflare_r2_bucket_lifecycle.ci.rules :
      r.enabled && r.conditions.prefix == "" && r.abort_multipart_uploads_transition != null
    ])
    error_message = "Managing lifecycle replaces R2's default multipart-abort rule, so it must be restated."
  }

  assert {
    condition = (
      tolist([for r in cloudflare_r2_bucket_lifecycle.ci.rules : r.id])
      == sort([for r in cloudflare_r2_bucket_lifecycle.ci.rules : r.id])
    )
    error_message = "R2 returns lifecycle rules sorted by id; any other order is a perpetual diff."
  }
}

run "repo_gets_ci_secrets_and_variables" {
  command = plan

  assert {
    condition = toset([for s in github_actions_secret.ci : s.secret_name]) == toset([
      "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "ANTHROPIC_API_KEY",
    ])
    error_message = "Repo secrets must be exactly the R2 key pair and ANTHROPIC_API_KEY."
  }

  assert {
    condition     = github_actions_secret.ci["ANTHROPIC_API_KEY"].value == "sk-ant-test"
    error_message = "ANTHROPIC_API_KEY must come from var.anthropic_api_key."
  }

  assert {
    condition     = github_actions_variable.ci["R2_ENDPOINT"].value == "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
    error_message = "R2_ENDPOINT must be the account's S3 endpoint."
  }

  assert {
    condition     = github_actions_variable.ci["R2_BUCKET"].value == "somewpilib-ci"
    error_message = "R2_BUCKET must name the CI bucket."
  }

  assert {
    condition     = alltrue([for s in github_actions_secret.ci : s.repository == "somewpilib"])
    error_message = "Secrets must land on the fork repo."
  }
}

run "actions_enabled_and_upstream_schedules_disabled" {
  command = plan

  assert {
    condition     = github_actions_repository_permissions.repo.enabled
    error_message = "Actions must be enabled."
  }

  assert {
    condition = toset(terraform_data.disable_upstream_schedules.input) == toset([
      "artifactory-nightly-cleanup.yml", "sentinel-build.yml",
    ])
    error_message = "Both upstream scheduled workflows must be disabled."
  }
}

run "short_state_passphrase_is_rejected" {
  command = plan

  variables {
    state_passphrase = "too-short"
  }

  expect_failures = [var.state_passphrase]
}
