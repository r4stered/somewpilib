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

# CI's S3 credentials.
module "ci_token" {
  source = "./modules/r2-bucket-token"

  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.ci.name
  token_name  = "${var.github_repository} CI (${local.ci_bucket})"
}
