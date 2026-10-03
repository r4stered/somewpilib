#!/usr/bin/env python3
"""CI's dependency cache: the provider's built deps, stored in R2 (#7, #30).

The provider puts everything it fetches under WPILIB_DEPS_DIR/download/ and
everything it installs under WPILIB_DEPS_DIR/prefix/. One tarball of both is
stored per key, at deps/<os>-<arch>-<compiler>-<hash>.tar.gz. The hash covers
every file that decides what the provider builds (KEY_INPUTS), the
WPILIB_DEP_* configure arguments and the build type, so a key is never rewritten: a change makes
a new key, and the bucket's lifecycle rule ages out the old one.

The restore and save steps of .fork/ci/dep-cache/ run this. Cache trouble is
never a build failure: a store error is a warning and a miss.
"""

import argparse
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

# Bump to invalidate every key, e.g. when the tarball layout changes.
KEY_VERSION = "1"

# Globs, relative to the repo root, for the files that decide what the provider
# builds: its recipes, the pins (upstream's tag lines and the fork's pin table)
# and the fork's patches. A recipe or pin file outside these must be added here.
KEY_INPUTS = (
    ".fork/cmake/dependencies.cmake",
    ".fork/cmake/stock.cmake",
    ".fork/cmake/stock-fetch.cmake",
    ".fork/cmake/deps/**/*",
    ".fork/pin*",
    ".fork/patches/**/*",
    "upstream_utils/*.py",
)

# The subdirectories of WPILIB_DEPS_DIR that are cached. Build trees are not.
CACHED_DIRS = ("download", "prefix")

OBJECT_PREFIX = "deps/"


class StoreError(Exception):
    pass


# Configure definitions that change what the provider builds. The build type is
# one: an MSVC Debug build links a different runtime.
KEY_DEFINITIONS = ("WPILIB_DEP_", "CMAKE_BUILD_TYPE=", "CMAKE_BUILD_TYPE:")


def dep_args(configure_args):
    """The definitions in a configure command line that enter the key, sorted.

    The workflow expands the arguments unquoted, so they are split the way
    bash does it: on whitespace, with any quote characters kept.
    """
    tokens = configure_args.split()
    defs = []
    for i, token in enumerate(tokens):
        if token == "-D" and i + 1 < len(tokens):
            defs.append(tokens[i + 1])
        elif token.startswith("-D") and len(token) > 2:
            defs.append(token[2:])
    return sorted(d for d in defs if d.startswith(KEY_DEFINITIONS))


def _input_files(root):
    root = pathlib.Path(root)
    files = set()
    for pattern in KEY_INPUTS:
        files.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(files)


def cache_key(root, os_name, arch, compiler, configure_args):
    """<os>-<arch>-<compiler>-<hash(recipes, pins, WPILIB_DEP_* args)>."""
    root = pathlib.Path(root)
    h = hashlib.sha256(f"v{KEY_VERSION}\n".encode())
    for path in _input_files(root):
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        h.update(f"file {rel} {digest}\n".encode())
    for d in dep_args(configure_args):
        h.update(f"arg {d}\n".encode())
    key = f"{os_name}-{arch}-{compiler}-{h.hexdigest()[:16]}".lower()
    if not re.fullmatch(r"[a-z0-9._-]+", key):
        raise ValueError(f"unsafe characters in dep cache key {key!r}")
    return key


def _object_name(key):
    return f"{OBJECT_PREFIX}{key}.tar.gz"


def restore(store, key, deps_dir):
    """Unpacks the key's tarball into deps_dir. Returns whether it was a hit."""
    name = _object_name(key)
    if not store.exists(name):
        return False
    deps_dir = pathlib.Path(deps_dir)
    deps_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = pathlib.Path(tmp) / "deps.tar.gz"
        store.download(name, archive)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                # The data filter refuses absolute paths, "..", and links that
                # point out of deps_dir.
                tar.extractall(deps_dir, filter="data")
        except (tarfile.TarError, OSError) as e:
            # Recipes reuse whatever they find, so a partial extract must go.
            for d in CACHED_DIRS:
                shutil.rmtree(deps_dir / d, ignore_errors=True)
            raise StoreError(f"unusable tarball {name}: {e}") from e
    return True


def save(store, key, deps_dir, write):
    """Uploads deps_dir's cached dirs under key, unless there is no need.

    Returns what happened: "read-only", "exists", "empty" or "uploaded".
    """
    if not write:
        return "read-only"
    name = _object_name(key)
    if store.exists(name):
        return "exists"
    deps_dir = pathlib.Path(deps_dir)
    present = [d for d in CACHED_DIRS if (deps_dir / d).is_dir()]
    if not present:
        return "empty"
    with tempfile.TemporaryDirectory() as tmp:
        archive = pathlib.Path(tmp) / "deps.tar.gz"
        try:
            with tarfile.open(archive, "w:gz") as tar:
                for d in present:
                    tar.add(deps_dir / d, arcname=d)
        except OSError as e:
            raise StoreError(f"could not pack {deps_dir}: {e}") from e
        store.upload(archive, name)
    return "uploaded"


class S3Store:
    """The R2 bucket, reached through the runner's aws CLI."""

    def __init__(self, bucket, endpoint):
        self.bucket = bucket
        self.endpoint = endpoint

    def _aws(self, *args):
        env = dict(os.environ, AWS_DEFAULT_REGION="auto")
        try:
            return subprocess.run(
                ["aws", *args, "--endpoint-url", self.endpoint],
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError as e:
            raise StoreError("the aws CLI is not installed") from e

    def _check(self, result):
        if result.returncode != 0:
            raise StoreError(result.stderr.strip() or f"aws exited {result.returncode}")

    def exists(self, name):
        result = self._aws("s3api", "head-object", "--bucket", self.bucket, "--key", name)
        if result.returncode != 0 and ("404" in result.stderr or "Not Found" in result.stderr):
            return False
        self._check(result)
        return True

    def download(self, name, path):
        self._check(
            self._aws("s3", "cp", "--only-show-errors", f"s3://{self.bucket}/{name}", str(path))
        )

    def upload(self, path, name):
        self._check(
            self._aws("s3", "cp", "--only-show-errors", str(path), f"s3://{self.bucket}/{name}")
        )


def _set_output(name, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("key", "restore", "save"))
    parser.add_argument("--root", default=".", help="the repo root")
    parser.add_argument("--deps-dir", default="build-cmake/_wpilib_deps")
    parser.add_argument("--os", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--compiler", required=True)
    parser.add_argument("--configure-args", default="")
    parser.add_argument("--write", action="store_true", help="save may upload")
    args = parser.parse_args(argv)

    key = cache_key(args.root, args.os, args.arch, args.compiler, args.configure_args)
    print(f"dep cache key: {key}")
    _set_output("key", key)
    if args.command == "key":
        return 0

    store = S3Store(os.environ["R2_BUCKET"], os.environ["R2_ENDPOINT"])
    start = time.monotonic()
    try:
        if args.command == "restore":
            hit = restore(store, key, args.deps_dir)
            print("dep cache: hit" if hit else "dep cache: miss")
            _set_output("hit", str(hit).lower())
        else:
            outcome = save(store, key, args.deps_dir, args.write)
            print(f"dep cache save: {outcome}")
    except StoreError as e:
        print(f"::warning title=dep cache::{args.command} skipped: {e}")
        if args.command == "restore":
            _set_output("hit", "false")
    print(f"dep cache: {args.command} took {time.monotonic() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
