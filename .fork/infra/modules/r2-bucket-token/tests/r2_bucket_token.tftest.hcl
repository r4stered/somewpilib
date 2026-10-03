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

  mock_resource "cloudflare_account_token" {
    defaults = {
      id    = "token-id"
      value = "token-value"
    }
  }
}

variables {
  account_id  = "0123456789abcdef0123456789abcdef"
  bucket_name = "some-bucket"
  token_name  = "some token"
}

run "token_is_scoped_to_one_bucket_with_item_access_only" {
  command = plan

  assert {
    condition = toset(flatten([
      for p in cloudflare_account_token.this.policies : [for g in p.permission_groups : g.id]
    ])) == toset(["pg-item-read", "pg-item-write"])
    error_message = "Token must hold only the bucket-item read/write permission groups."
  }

  assert {
    condition = alltrue([
      for p in cloudflare_account_token.this.policies :
      keys(jsondecode(p.resources)) == ["com.cloudflare.edge.r2.bucket.0123456789abcdef0123456789abcdef_default_some-bucket"]
    ])
    error_message = "Token must be scoped to the named bucket, not the whole account."
  }
}

run "s3_keys_are_derived_from_the_token" {
  assert {
    condition     = output.access_key_id == "token-id"
    error_message = "R2's access key ID is the token ID."
  }

  assert {
    condition     = output.secret_access_key == sha256("token-value")
    error_message = "R2's secret access key is the SHA-256 of the token value."
  }
}

run "missing_permission_groups_fail_the_plan" {
  command = plan

  override_data {
    target = data.cloudflare_account_api_token_permission_groups_list.all
    values = { result = [] }
  }

  expect_failures = [cloudflare_account_token.this]
}
