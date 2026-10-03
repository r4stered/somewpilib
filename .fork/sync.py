#!/usr/bin/env python3
"""Fork tooling: the removal manifest, prune and the tree invariants.

The removal manifest (.fork/manifest) is a gitignore-style deny-list. A path
it matches is removed; any other path is carried. Unlike gitignore, a later
negation can re-include a file under a directory an earlier pattern removed:
every pattern is tested against the file and each of its ancestor
directories, and the last pattern that matches decides.
"""

import argparse
import collections
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    text: str
    negated: bool
    regex: re.Pattern


def _glob_to_regex(glob):
    out = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i) and (i == 0 or glob[i - 1] == "/"):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            out.append("/.*")
            i += 3
        elif c == "*":
            # Any other run of stars is one ordinary star, as in gitignore.
            while glob.startswith("*", i):
                i += 1
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            end = glob.find("]", i + 2)
            if end == -1:
                out.append(re.escape(c))
                i += 1
                continue
            body = glob[i + 1 : end]
            negate = body.startswith("!")
            if negate:
                body = body[1:]
            body = body.replace("\\", "\\\\").replace("[", "\\[")
            # A class never matches a slash, negated or not.
            out.append(f"(?!/)[{'^' if negate else ''}{body}]")
            i = end + 1
        elif c == "\\" and i + 1 < len(glob):
            out.append(re.escape(glob[i + 1]))
            i += 2
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _parse_pattern(line):
    negated = line.startswith("!")
    if negated:
        line = line[1:]
    elif line.startswith("\\"):
        line = line[1:]
    dir_only = line.endswith("/")
    body = line.rstrip("/")
    # Like gitignore, a pattern with no slash but a trailing one matches at
    # any depth; any other slash anchors it to the repo root.
    anchored = "/" in body
    body = body.lstrip("/")
    regex = _glob_to_regex(body)
    if not anchored:
        regex = "(?:.*/)?" + regex
    # One regex tests the file and all its ancestors: a match on an ancestor
    # directory leaves a "/..." tail, a match on the file itself leaves none.
    regex += "/.+" if dir_only else "(?:/.+)?"
    return Pattern(line, negated, re.compile(regex + r"\Z", re.DOTALL))


class Manifest:
    def __init__(self, patterns):
        self.patterns = patterns

    @classmethod
    def parse(cls, text):
        patterns = []
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            patterns.append(_parse_pattern(line))
        return cls(patterns)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.parse(f.read())

    def removes(self, path):
        """Whether the manifest removes this repo-relative file path."""
        for pattern in reversed(self.patterns):
            if pattern.regex.match(path):
                return not pattern.negated
        return False


def _git(root, *args, stdin=None):
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=root,
        input=stdin,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        env=env,
    ).stdout


def _nul_split(text):
    return [p for p in text.split("\0") if p]


def _remove_empty_parents(root, path):
    parent = (pathlib.Path(root) / path).parent
    while parent != pathlib.Path(root):
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def prune(root, manifest):
    """Delete every file the manifest removes from the index and working tree.

    Covers tracked files and untracked, non-ignored ones (such as a
    generator's output written into a removed path). Returns the removed
    paths, sorted.
    """
    tracked = set(_nul_split(_git(root, "ls-files", "-z", "--cached")))
    untracked = set(
        _nul_split(_git(root, "ls-files", "-z", "--others", "--exclude-standard"))
    )
    removed_tracked = sorted(p for p in tracked if manifest.removes(p))
    # A nested repository shows up as "dir/"; deleting one is left to a human,
    # and check() still reports it.
    removed_untracked = sorted(
        p for p in untracked if manifest.removes(p) and not p.endswith("/")
    )
    if removed_tracked:
        _git(
            root,
            "rm",
            "-q",
            "-f",
            "--ignore-unmatch",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            stdin="\0".join(removed_tracked),
        )
    for path in removed_untracked:
        (pathlib.Path(root) / path).unlink()
        _remove_empty_parents(root, path)
    return sorted(removed_tracked + removed_untracked)


class ModifySurface:
    """The carried-file edits the fork makes (.fork/modify-surface.txt).

    One entry per line, as `<path> +<added line>` or `<path> -<removed line>`,
    in the form carried_edits() reports them.
    """

    def __init__(self, entries):
        self.entries = collections.Counter(entries)

    @classmethod
    def parse(cls, text):
        entries = []
        for raw in text.split("\n"):
            if not raw.strip() or raw.startswith("#"):
                continue
            entries.append(raw)
        return cls(entries)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.parse(f.read())


def _file_edits(root, base, path):
    diff = _git(
        root,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--unified=0",
        base,
        "--",
        path,
    )
    edits = []
    in_hunk = False
    old_mode = None
    for line in diff.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line[:1] in ("+", "-"):
            edits.append(f"{path} {line}")
        elif not in_hunk and line.startswith("old mode "):
            old_mode = line.removeprefix("old mode ")
        elif not in_hunk and line.startswith("new mode "):
            edits.append(f"{path} (mode {old_mode} -> {line.removeprefix('new mode ')})")
        elif line.startswith("Binary files "):
            edits.append(f"{path} (binary)")
    return edits


def carried_edits(root, manifest, base):
    """Every edit the working tree makes to carried files, relative to base.

    A carried file is one that exists in base and that the manifest doesn't
    remove. Files added since base (the fork's own tooling) aren't carried.
    """
    fields = _nul_split(
        _git(root, "diff", "--name-status", "-z", "--no-renames", base)
    )
    edits = []
    for status, path in zip(fields[::2], fields[1::2]):
        if status == "A" or manifest.removes(path):
            continue
        if status == "D":
            edits.append(f"{path} (deleted)")
        elif status == "T":
            edits.append(f"{path} (type change)")
        else:
            edits.extend(_file_edits(root, base, path))
    return edits


def check(root, manifest, surface, base, require_surface=True):
    """Check the tree invariants and return the violations (empty = pass).

    - No path the manifest removes exists, tracked or untracked.
    - The edits to carried files equal the modify surface. With
      require_surface=False, only edits beyond the surface are violations,
      so a tree that doesn't have the surface yet still passes.
    """
    violations = []
    present = _nul_split(
        _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    )
    for path in sorted(set(present)):
        if manifest.removes(path):
            violations.append(f"manifest path exists: {path}")

    edits = collections.Counter(carried_edits(root, manifest, base))
    for entry in sorted((edits - surface.entries).elements()):
        violations.append(f"carried edit not in modify surface: {entry}")
    if require_surface:
        for entry in sorted((surface.entries - edits).elements()):
            violations.append(f"modify-surface entry missing from the tree: {entry}")
    return violations


def _report(violations):
    for v in violations:
        print(f"error: {v}", file=sys.stderr)
    return 1 if violations else 0


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["prune", "check"])
    parser.add_argument(
        "--upstream",
        default="upstream/main",
        help="upstream ref; the base is its merge-base with HEAD (default: %(default)s)",
    )
    parser.add_argument(
        "--base", help="compare carried files against this ref instead"
    )
    args = parser.parse_args(argv)

    root = pathlib.Path(root or pathlib.Path(__file__).resolve().parents[1])
    manifest = Manifest.load(root / ".fork/manifest")
    surface = ModifySurface.load(root / ".fork/modify-surface.txt")
    try:
        base = args.base or _git(root, "merge-base", "HEAD", args.upstream).strip()
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: no merge-base with {args.upstream}: {e.stderr.strip()}")

    if args.command == "prune":
        removed = prune(root, manifest)
        print(f"pruned {len(removed)} paths")
        # The modify surface is made after the prune (birth commit 3), so a
        # freshly pruned tree only has to be free of edits beyond it.
        return _report(check(root, manifest, surface, base, require_surface=False))
    return _report(check(root, manifest, surface, base))


if __name__ == "__main__":
    sys.exit(main())
