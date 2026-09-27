output "ci_bucket" {
  value = cloudflare_r2_bucket.ci.name
}

output "r2_endpoint" {
  value = local.r2_endpoint
}
