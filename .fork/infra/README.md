# Fork infrastructure (OpenTofu)

This directory holds Step 0 of the removal spec (r4stered/somewpilib#27) as OpenTofu config.

| Resource | What it is |
|---|---|
| `cloudflare_r2_bucket.ci` | The `somewpilib-ci` bucket that holds `sccache/` and `deps/`. |
| `cloudflare_r2_bucket_lifecycle.ci` | Deletes objects older than 30 days under `sccache/` and `deps/`, and aborts multipart uploads older than 7 days. It restates R2's default abort rule because this resource replaces the bucket's whole rule set. |
| `module.ci_token` | An account-owned token with item read/write on the CI bucket only. CI's S3 keys are derived from it. |
| `github_actions_secret.ci` | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `ANTHROPIC_API_KEY`. |
| `github_actions_variable.ci` | `R2_BUCKET` and `R2_ENDPOINT`. Neither is secret. |
| `github_actions_repository_permissions.repo` | Turns Actions on. |
| `terraform_data.disable_upstream_schedules` | Runs `gh workflow disable` on upstream's two scheduled workflows as soon as Actions is on. They stay on `main` until the birth merge deletes them. |

The `upstream` remote is local git config, so it isn't managed here (see [After apply](#after-apply)).

There are two configs, and both keep their state in the `somewpilib-tofu-state` R2 bucket, under different keys:

- **`bootstrap/`** creates that bucket (with `prevent_destroy`) and a token scoped to it. The token supplies the S3 keys both backends use.
- **This directory** holds everything else.

`modules/r2-bucket-token/` is the shared "token for one bucket, exposed as S3 keys" piece that both configs use.

## Before you start (by hand)

1. Under **Manage account → Account API tokens**, create the token OpenTofu will use, with these permissions:
   - Account · Workers R2 Storage · Edit
   - Account · Account API Tokens · Edit
2. Choose a state passphrase of at least 16 characters and store it in a password manager. **If you lose it, neither state can be read.** Both configs use it.

```bash
export CLOUDFLARE_API_TOKEN="<token from step 1>"
export TF_VAR_cloudflare_account_id="<account-id>"
export TF_VAR_state_passphrase="<passphrase>"
```

## Bootstrap (once)

The state bucket doesn't exist yet, so the first apply runs on local state and then moves that state into the bucket it just created:

```bash
cd bootstrap
printf 'terraform {\n  backend "local" {}\n}\n' > local_override.tf   # gitignored
tofu init
tofu apply

export AWS_ENDPOINT_URL_S3="$(tofu output -raw endpoint)"
export AWS_ACCESS_KEY_ID="$(tofu output -raw access_key_id)"
export AWS_SECRET_ACCESS_KEY="$(tofu output -raw secret_access_key)"

rm local_override.tf
tofu init -migrate-state && rm -f terraform.tfstate terraform.tfstate.backup   # answer "yes"
cd ..
```

Save the three `AWS_*` values in your password manager next to the passphrase. Later sessions need them just to reach either state, so they can't be read back from `tofu output`.

## Environment for the main config

On top of the variables above and the three `AWS_*` ones:

```bash
export GITHUB_TOKEN="$(gh auth token)"
export TF_VAR_anthropic_api_key="<key>"
```

`gh` must be logged in as a repo admin, because the workflow-disable step runs through it.

## Apply

> **Once this is applied, don't push any branch that still carries upstream's workflows.** Once Actions is on, `bazel.yml`, `cmake.yml`, `gradle.yml` and the others run on every push to any branch. `birth` is safe to push only after commit 2 (the prune) has deleted them.

```bash
tofu init
tofu plan -out=step0.tfplan
tofu apply step0.tfplan
```

To rotate CI's R2 keys, run `tofu apply -replace=module.ci_token.cloudflare_account_token.this`. The repo secrets follow automatically.

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

Run this in each of `.`, `bootstrap/` and `modules/r2-bucket-token/`:

```bash
tofu init -backend=false
tofu test
```

The tests plan against mocked providers, so they need no credentials.
