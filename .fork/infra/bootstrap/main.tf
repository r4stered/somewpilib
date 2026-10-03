variable "cloudflare_account_id" {
  description = "Cloudflare account that owns the R2 buckets."
  type        = string
}

variable "state_passphrase" {
  description = "Passphrase for OpenTofu's client-side state and plan encryption."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.state_passphrase) >= 16
    error_message = "The pbkdf2 key provider needs a passphrase of at least 16 characters."
  }
}

# Holds this config's state and the main config's. Deleting it loses both.
resource "cloudflare_r2_bucket" "state" {
  account_id = var.cloudflare_account_id
  name       = "somewpilib-tofu-state"

  lifecycle {
    prevent_destroy = true
  }
}

# The backend credentials for both configs.
module "state_token" {
  source = "../modules/r2-bucket-token"

  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.state.name
  token_name  = "OpenTofu state (${cloudflare_r2_bucket.state.name})"
}

output "endpoint" {
  description = "Value for AWS_ENDPOINT_URL_S3."
  value       = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com"
}

output "access_key_id" {
  description = "Value for AWS_ACCESS_KEY_ID."
  value       = module.state_token.access_key_id
}

output "secret_access_key" {
  description = "Value for AWS_SECRET_ACCESS_KEY."
  value       = module.state_token.secret_access_key
  sensitive   = true
}
