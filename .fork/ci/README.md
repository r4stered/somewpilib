# Fork CI

| File | What it is |
|---|---|
| `install-linux-deps.sh` | The system packages a stock Linux runner needs. |
| `dep-cache/` | The composite action that restores and saves the provider's built dependencies. |
| `dep_cache.py` | The key, restore and save logic behind `dep-cache/`. Tests: `python3 -m unittest discover -s .fork/tests`. |

## The R2 cache

Every cache lives in one Cloudflare R2 bucket, `somewpilib-ci`. It was created in Step 0 (r4stered/somewpilib#27) by the OpenTofu config in [`.fork/infra/`](../infra/README.md), which also sets up the credentials below. The design is in #6 and #7.

| Prefix | What it holds | Written by |
|---|---|---|
| `sccache/` | sccache's compile objects, one per compilation. | sccache itself (`SCCACHE_S3_KEY_PREFIX`) |
| `deps/` | One `<key>.tar.gz` per dep-cache key, holding the provider's `download/` and `prefix/` dirs. | `dep-cache/` |

### Credentials

OpenTofu sets these on the repo:

- Variables: `R2_BUCKET`, the bucket name, and `R2_ENDPOINT`, `https://<account-id>.r2.cloudflarestorage.com`.
- Secrets: `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`. These are S3 keys for an account token that can read and write objects in this bucket and nothing else.

R2 has no regions, so sccache uses `SCCACHE_REGION=auto` and `dep_cache.py` sets `AWS_DEFAULT_REGION=auto`. To rotate the keys, see the infra README.

### Who writes

- **`main` pushes** (and the sync workflow, once it exists) write. sccache runs with `SCCACHE_S3_RW_MODE=READ_WRITE`, and `dep-cache` gets `write: true`.
- **Everything else only reads.** On a PR, sccache runs `READ_ONLY`, and `dep-cache` save does nothing. A PR miss builds from source and uploads nothing, so a PR can never poison the cache that `main` reads.
- **No secret, no cache.** A PR from a fork of the fork gets no secrets. The workflow then doesn't install sccache or set the compiler launcher, and both `dep-cache` steps log a notice and do nothing. The build passes, just slower.

Cache trouble never fails a build. sccache runs with `SCCACHE_IGNORE_SERVER_IO_ERROR=1`, so it compiles locally when the bucket can't be reached. `dep_cache.py` turns any store error, or a tarball it can't unpack, into a warning and a miss, and deletes a partial extract first.

Read-only is enforced by the job's settings, not by the token. The one R2 token can write, and a same-repo PR gets it. That's safe because anyone who can push a same-repo branch can already edit the workflow. PRs from forks of the fork get no secret at all.

### The dep-cache key

```
deps/<os>-<arch>-<compiler>-<hash>.tar.gz
e.g. deps/linux-x64-gcc-15-900909bf2b755d24.tar.gz
```

- `<os>` and `<arch>` are the runner's `runner.os` and `runner.arch`, lowercased.
- `<compiler>` is the row's C compiler (`matrix.cc`, e.g. `gcc-15`). Rows pin the compiler major, so a major bump is a new key.
- `<hash>` is the first 16 hex digits of a SHA-256 over:
  - every file matching `KEY_INPUTS` in `dep_cache.py`, by path and whole content. These are the provider and its recipes, the pins (every `upstream_utils/*.py`, where upstream's tag lines live, and the fork's pin table) and `.fork/patches/`. So any edit to one of them, even a comment, makes a new key;
  - the `WPILIB_DEP_*` and `CMAKE_BUILD_TYPE` definitions in the row's `CONFIGURE_ARGS`, sorted. The build type is there because an MSVC Debug build links a different runtime. Other arguments don't affect what the provider builds, so they don't enter the key. A row whose deps differ some other way, such as a sanitizer row that instruments them, must put the difference in a `WPILIB_DEP_*` argument;
  - `KEY_VERSION`, which you bump to invalidate every key.

**When you add a recipe or pin file outside those globs, add it to `KEY_INPUTS`.** Otherwise a change to it will restore a stale prefix.

A key's contents never change, so an object is never overwritten. Save skips any key that already exists, and a changed input makes a new key. Old keys are never deleted by CI. The lifecycle rule ages them out.

### What the provider must do

The provider keeps its work under `WPILIB_DEPS_DIR`, which defaults to `<build>/_wpilib_deps` ([`dependencies.cmake`](../cmake/dependencies.cmake)):

- `download/<dep>/`: fetched sources (cached);
- `prefix/<dep>/`: install prefixes (cached);
- anything else, such as build trees: not cached.

`dep-cache` restores into `build-cmake/_wpilib_deps` before configure. A recipe that finds its `download/` or `prefix/` dir already populated must use it, not fetch or build again. That is what turns a restore into a skipped build.

### Lifecycle rule

The bucket has one lifecycle rule set. It is managed by `cloudflare_r2_bucket_lifecycle.ci` in [`.fork/infra/r2.tf`](../infra/r2.tf), not in the dashboard:

- objects under `sccache/` and `deps/` are deleted 30 days after upload;
- incomplete multipart uploads are aborted after 7 days.

R2 ages objects from their upload, not their last read. Even a hot `deps/` object therefore expires after 30 days, and the next `main` run rebuilds and re-uploads it. That is the only eviction there is. Nothing caps the bucket's size, and nothing needs to while it stays within a few GB. R2's first 10 GB-month is free, after that it's about $0.015 per GB-month, and downloads are free.

### Checking it

- A `main` run's post-job "sccache stats" and its `Save the dep cache` step show writes (`dep cache save: uploaded` on a cold key).
- A PR run's `Restore the dep cache` step prints the key and `hit` or `miss`. Its save step prints `read-only`, and sccache's stats show hits and no writes.
- `aws s3 ls s3://somewpilib-ci/deps/ --endpoint-url "$R2_ENDPOINT"` lists the dep tarballs.
