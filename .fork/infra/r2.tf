locals {
  ci_bucket   = "somewpilib-ci"
  r2_endpoint = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com"

  # CI rewrites these prefixes from main only; stale objects age out instead of
  # being evicted.
  cache_prefixes        = ["sccache/", "deps/"]
  cache_max_age_seconds = 30 * 24 * 60 * 60
}

resource "cloudflare_r2_bucket" "ci" {
  account_id = var.cloudflare_account_id
  name       = local.ci_bucket
}

resource "cloudflare_r2_bucket_lifecycle" "ci" {
  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.ci.name

  # This resource owns the bucket's whole rule set, so it replaces the
  # multipart-abort rule R2 gives new buckets by default. Restate it.
  rules = concat(
    [{
      id         = "abort-stale-multipart-uploads"
      enabled    = true
      conditions = { prefix = "" }
      abort_multipart_uploads_transition = {
        condition = { type = "Age", max_age = 7 * 24 * 60 * 60 }
      }
    }],
    [for prefix in local.cache_prefixes : {
      id         = "expire-${trimsuffix(prefix, "/")}"
      enabled    = true
      conditions = { prefix = prefix }
      delete_objects_transition = {
        condition = { type = "Age", max_age = local.cache_max_age_seconds }
      }
    }],
  )
}

data "cloudflare_account_api_token_permission_groups_list" "all" {
  account_id = var.cloudflare_account_id
}

locals {
  r2_item_permission_groups = [
    for g in data.cloudflare_account_api_token_permission_groups_list.all.result : g.id
    if contains(["Workers R2 Storage Bucket Item Read", "Workers R2 Storage Bucket Item Write"], g.name)
  ]
}

# CI's S3 credentials. R2 derives them from an API token: the access key ID is
# the token ID and the secret access key is the SHA-256 of the token value.
resource "cloudflare_account_token" "ci" {
  account_id = var.cloudflare_account_id
  name       = "${var.github_repository} CI (${local.ci_bucket})"

  policies = [{
    effect            = "allow"
    permission_groups = [for id in local.r2_item_permission_groups : { id = id }]
    resources = jsonencode({
      "com.cloudflare.edge.r2.bucket.${var.cloudflare_account_id}_default_${local.ci_bucket}" = "*"
    })
  }]

  lifecycle {
    precondition {
      condition     = length(local.r2_item_permission_groups) == 2
      error_message = "Could not find both R2 bucket-item permission groups; Cloudflare may have renamed them."
    }
  }
}
