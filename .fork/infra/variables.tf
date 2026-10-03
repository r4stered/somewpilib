variable "cloudflare_account_id" {
  description = "Cloudflare account that owns the R2 buckets."
  type        = string
}

variable "github_owner" {
  description = "Owner of the fork repo."
  type        = string
  default     = "r4stered"
}

variable "github_repository" {
  description = "Name of the fork repo."
  type        = string
  default     = "somewpilib"
}

variable "anthropic_api_key" {
  description = "Stored as the ANTHROPIC_API_KEY repo secret for the sync workflow's reviewer."
  type        = string
  sensitive   = true
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
