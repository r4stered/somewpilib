terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.26"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.13"
    }
  }

  # State lives in a hand-made R2 bucket (see README, "Bootstrap"). The
  # account-specific endpoint comes from AWS_ENDPOINT_URL_S3 and the
  # credentials from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
  backend "s3" {
    bucket = "somewpilib-tofu-state"
    key    = "infra/terraform.tfstate"
    region = "auto"

    use_path_style              = true
    use_lockfile                = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }

  # State and plans hold the R2 secret key and ANTHROPIC_API_KEY, so both are
  # encrypted client-side before they reach the backend.
  encryption {
    key_provider "pbkdf2" "state" {
      passphrase = var.state_passphrase
    }

    method "aes_gcm" "state" {
      keys = key_provider.pbkdf2.state
    }

    state {
      method   = method.aes_gcm.state
      enforced = true
    }

    plan {
      method   = method.aes_gcm.state
      enforced = true
    }
  }
}

# Both providers read their credentials from the environment:
# CLOUDFLARE_API_TOKEN and GITHUB_TOKEN.
provider "cloudflare" {}

provider "github" {
  owner = var.github_owner
}
