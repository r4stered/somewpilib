# An account-owned API token with object read/write on a single R2 bucket,
# exposed as S3 credentials. R2 derives those from the token: the access key ID
# is the token ID and the secret access key is the SHA-256 of the token value.

terraform {
  required_providers {
    cloudflare = {
      source = "cloudflare/cloudflare"
    }
  }
}

variable "account_id" {
  description = "Cloudflare account that owns the bucket."
  type        = string
}

variable "bucket_name" {
  description = "The only bucket the token can reach."
  type        = string
}

variable "token_name" {
  description = "Display name of the token in the Cloudflare dashboard."
  type        = string
}

data "cloudflare_account_api_token_permission_groups_list" "all" {
  account_id = var.account_id
}

locals {
  item_permission_groups = [
    for g in data.cloudflare_account_api_token_permission_groups_list.all.result : g.id
    if contains(["Workers R2 Storage Bucket Item Read", "Workers R2 Storage Bucket Item Write"], g.name)
  ]
}

resource "cloudflare_account_token" "this" {
  account_id = var.account_id
  name       = var.token_name

  policies = [{
    effect            = "allow"
    permission_groups = [for id in local.item_permission_groups : { id = id }]
    resources = jsonencode({
      "com.cloudflare.edge.r2.bucket.${var.account_id}_default_${var.bucket_name}" = "*"
    })
  }]

  lifecycle {
    precondition {
      condition     = length(local.item_permission_groups) == 2
      error_message = "Could not find both R2 bucket-item permission groups; Cloudflare may have renamed them."
    }
  }
}

output "access_key_id" {
  description = "S3 access key ID for the bucket."
  value       = cloudflare_account_token.this.id
}

output "secret_access_key" {
  description = "S3 secret access key for the bucket."
  value       = sha256(cloudflare_account_token.this.value)
  sensitive   = true
}
