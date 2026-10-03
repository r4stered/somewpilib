# Plan-only checks against a mocked provider. Run with `tofu test` from
# .fork/infra/bootstrap; no credentials or network access are needed.

mock_provider "cloudflare" {
  mock_data "cloudflare_account_api_token_permission_groups_list" {
    defaults = {
      result = [
        { id = "pg-item-read", name = "Workers R2 Storage Bucket Item Read", scopes = ["com.cloudflare.edge.r2.bucket"] },
        { id = "pg-item-write", name = "Workers R2 Storage Bucket Item Write", scopes = ["com.cloudflare.edge.r2.bucket"] },
      ]
    }
  }
}

variables {
  cloudflare_account_id = "0123456789abcdef0123456789abcdef"
  state_passphrase      = "a-test-passphrase-that-is-long"
}

run "state_bucket_is_the_one_both_backends_use" {
  command = plan

  assert {
    condition     = cloudflare_r2_bucket.state.name == "somewpilib-tofu-state"
    error_message = "State bucket name changed."
  }

  assert {
    condition = alltrue([
      for f in ["${path.module}/versions.tf", "${path.module}/../versions.tf"] :
      can(regex("bucket\\s*=\\s*\"${cloudflare_r2_bucket.state.name}\"", file(f)))
    ])
    error_message = "Both backends must point at the bucket bootstrap creates."
  }

  assert {
    condition = (
      regex("key\\s*=\\s*\"([^\"]+)\"", file("${path.module}/versions.tf"))[0]
      != regex("key\\s*=\\s*\"([^\"]+)\"", file("${path.module}/../versions.tf"))[0]
    )
    error_message = "Bootstrap and main state must use different keys in the shared bucket."
  }
}

run "short_state_passphrase_is_rejected" {
  command = plan

  variables {
    state_passphrase = "too-short"
  }

  expect_failures = [var.state_passphrase]
}
