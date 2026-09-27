# Contributing to somewpilib

This fork carries upstream WPILib almost unchanged. Most fixes belong upstream. Report bugs in WPILib's own code at [wpilibsuite/allwpilib](https://github.com/wpilibsuite/allwpilib), and they reach this fork through the weekly sync. Issues with the fork itself (its build, dependency provider, CI or sync) belong in this repository.

## Rules for fork changes

- **Don't edit carried files.** A carried file is any file upstream has and the fork keeps. The fork's whole diff against them is listed in [`.fork/modify-surface.txt`](../.fork/modify-surface.txt), which currently holds one line in the top-level `CMakeLists.txt`. Anything else goes in a fork-owned file.
- **Fork-owned files** live in `.fork/`, in `.github/workflows/fork-*.yml`, and in this directory's `README.md` and `CONTRIBUTING.md`.
- **Don't remove files by hand.** Removals come from the manifest, [`.fork/manifest`](../.fork/manifest). Edit it, then run `python3 .fork/sync.py prune`.
- Prefix commit subjects with `[fork]`.

## Checks

```bash
python3 .fork/sync.py check
python3 -m unittest discover -s .fork/tests
```

`sync.py check` fails if a path the manifest removes exists, or if the edits to carried files differ from the modify surface. It compares against the merge-base with `upstream/main`, so fetch the `upstream` remote first.
