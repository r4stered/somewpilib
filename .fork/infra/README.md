# Fork infrastructure (OpenTofu)

This directory holds Step 0 of the removal spec (r4stered/somewpilib#27) as OpenTofu config.

| Resource | What it is |
|---|---|
| `cloudflare_r2_bucket.ci` | The `somewpilib-ci` bucket that holds `sccache/` and `deps/`. |
| `cloudflare_r2_bucket_lifecycle.ci` | Deletes objects older than 30 days under `sccache/` and `deps/`, and aborts multipart uploads older than 7 days. It restates R2's default abort rule because this resource replaces the bucket's whole rule set. |
| `cloudflare_account_token.ci` | An account-owned token with item read/write on the CI bucket only. CI's S3 keys are derived from it. |
| `github_actions_secret.ci` | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `ANTHROPIC_API_KEY`. |
| `github_actions_variable.ci` | `R2_BUCKET` and `R2_ENDPOINT`. Neither is secret. |
| `github_actions_repository_permissions.repo` | Turns Actions on. |
| `terraform_data.disable_upstream_schedules` | Runs `gh workflow disable` on upstream's two scheduled workflows as soon as Actions is on. They stay on `main` until the birth merge deletes them. |

The `upstream` remote is local git config, so it isn't managed here (see [After apply](#after-apply)).

## Bootstrap (once, by hand)

State goes to its own R2 bucket, so that bucket and the credentials for it have to exist before `tofu init`.

1. In the Cloudflare dashboard, create the R2 bucket **`somewpilib-tofu-state`**.
2. Under **R2 → Manage API tokens**, create an **Object Read & Write** token scoped to `somewpilib-tofu-state`. Keep its Access Key ID and Secret Access Key.
3. Under **Manage account → Account API tokens**, create the token OpenTofu will use, with these permissions:
   - Account · Workers R2 Storage · Edit
   - Account · Account API Tokens · Edit
4. Choose a state passphrase of at least 16 characters and store it in a password manager. **If you lose it, the state can't be read.**

## Environment

```bash
export AWS_ENDPOINT_URL_S3="https://<account-id>.r2.cloudflarestorage.com"
export AWS_ACCESS_KEY_ID="<state bucket access key id>"
export AWS_SECRET_ACCESS_KEY="<state bucket secret access key>"
export CLOUDFLARE_API_TOKEN="<token from bootstrap step 3>"
export GITHUB_TOKEN="$(gh auth token)"
export TF_VAR_cloudflare_account_id="<account-id>"
export TF_VAR_state_passphrase="<passphrase>"
export TF_VAR_anthropic_api_key="<key>"
```

`gh` must be logged in as a repo admin, because the workflow-disable step runs through it.

## Apply

```bash
tofu init
tofu plan -out=step0.tfplan
tofu apply step0.tfplan
```

To rotate CI's R2 keys, run `tofu apply -replace=cloudflare_account_token.ci`. The repo secrets follow automatically.

## After apply

Add the `upstream` remote to each local checkout of the fork, as fetch-only:

```bash
git remote add upstream https://github.com/wpilibsuite/allwpilib.git
git remote set-url --push upstream DISABLED
```

Then check the acceptance criteria:

```bash
tofu plan                                          # "No changes": bucket and lifecycle rules match
gh secret list --repo r4stered/somewpilib           # R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, ANTHROPIC_API_KEY
gh variable list --repo r4stered/somewpilib         # R2_BUCKET, R2_ENDPOINT
gh workflow list --all --repo r4stered/somewpilib   # the two upstream schedules show disabled_manually
gh run list --repo r4stered/somewpilib              # empty
git remote -v                                       # upstream ... DISABLED (push)
```

## Using the values in workflows

sccache's S3 backend reads these environment variables:

```yaml
env:
  SCCACHE_BUCKET: ${{ vars.R2_BUCKET }}
  SCCACHE_ENDPOINT: ${{ vars.R2_ENDPOINT }}
  SCCACHE_REGION: auto
  SCCACHE_S3_KEY_PREFIX: sccache/
  AWS_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
  AWS_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
```

The `aws s3` calls in the dep cache use the same keys, with `--endpoint-url "$R2_ENDPOINT"` and objects under `deps/`.

## Tests

```bash
tofu init -backend=false
tofu test
```

The tests plan against mocked providers, so they need no credentials.
