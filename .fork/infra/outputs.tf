output "ci_bucket" {
  description = "Name of the CI cache bucket (also the R2_BUCKET repo variable)."
  value       = cloudflare_r2_bucket.ci.name
}

output "r2_endpoint" {
  description = "Account S3 endpoint for R2 (also the R2_ENDPOINT repo variable)."
  value       = local.r2_endpoint
}
