# Fork CMake

| File | What it is |
|---|---|
| `dependencies.cmake` | The provider entry file. The top-level `CMakeLists.txt` includes it at `project()` (the fork's one-line modify surface), and it includes everything below. |
| `stock.cmake` | The vendor-nothing mechanism: the functions every stock-library recipe calls. Tests: `python3 -m unittest discover -s .fork/tests`. |
| `stock-fetch.cmake` | The fetch step `stock.cmake` runs as `cmake -P`. |
| `deps/<lib>.cmake` | One recipe per stock library, named after its `upstream_utils/<lib>.py`. `dependencies.cmake` includes every file here. |
| `compile-workarounds.cmake` | Per-source flags for carried code (#57). |
| `version.cmake` | Version stamping (#10). |

## Stock libraries

Upstream commits its third-party libraries under `thirdparty/`. The fork removes them, and fetches each one **stock** instead (#12, ADR 0002). No carried file is edited to make that work. `deps/double-conversion.cmake` is the reference recipe.

### What happens at configure time

A recipe registers a deferred call, which runs once the top-level directory is done, so upstream's targets exist. The call does four things:

1. **Fetch and build.** `wpilib_stock_add()` clones the library at its tag, applies the fork's patches, and builds and installs it into `${WPILIB_DEPS_DIR}/prefix/<lib>`. It then imports the result with `find_package(<package> CONFIG)` and installs that prefix alongside WPILib.
   - It builds static and position-independent, the way upstream compiled its vendored copy into WPILib's own libraries, with WPILib's compilers and build type.
   - Under a multi-config generator it builds only `CMAKE_BUILD_TYPE`, or Release. The Windows rows (#43) have to settle Debug.
   - It can't use `add_subdirectory` instead, because CMake refuses to add subdirectories from a deferred call.
2. **Stand in for the removed dir.** `wpilib_stock_thirdparty_include()` recreates `thirdparty/<lib>/include`, so upstream's include lists and `install(DIRECTORY)` still resolve. It is empty unless the recipe writes shims into it with `wpilib_stock_shim()`. The recreated dir holds a `.gitignore` of `*`, so git, `sync.py prune` and the invariants never see it.
3. **Shim** (only if needed). A shim is a fork-owned header that maps upstream's renamed paths or namespaces onto stock. double-conversion's shims turn `wpi/double-conversion/*.h` into `<double-conversion/*.h>` and alias `wpi::double_conversion`.
4. **Wire.** `wpilib_stock_wire(<module> <imported target> <package>)` links the stock target into upstream's target, and makes the generated `<module>-config.cmake` call `find_dependency(<package>)` before it imports `<module>`'s targets.

### Which tag

The last one of these wins:

1. The `tag = "..."` line in the carried `upstream_utils/<lib>.py`. This keeps the fork in lockstep with upstream's library bumps for free.
2. The lib's entry in the **pin table**, [`.fork/pins.txt`](../pins.txt), used where the fork has to run ahead of upstream. Each entry records the upstream tag it overrides. Once upstream's `tag =` line changes, the entry is stale. The sync is to fail on a stale entry (#47), but nothing checks it yet.
3. `-DWPILIB_DEP_<LIB>_GIT_TAG=<tag>` for one build. `<LIB>` is the lib upper-cased, with `-` turned into `_`, e.g. `WPILIB_DEP_DOUBLE_CONVERSION_GIT_TAG`.

Configure logs which one it used, e.g. `double-conversion: v3.4.0 (upstream_utils/double-conversion.py)`.

`-DFETCHCONTENT_SOURCE_DIR_<LIB>=<dir>` builds a local checkout instead. It is built unpatched, and rebuilt on every configure. Here `<LIB>` keeps its `-`, as FetchContent spells it.

### Patches

`.fork/patches/<lib>/*.patch` are applied with `git apply`, in name order, after the fetch. Each one must have a line starting with `Exit condition:` above the diff, saying when it can be deleted. Configure fails on a patch without one. Once the condition holds, delete the patch.

### Caching

`download/<lib>` and `prefix/<lib>` under `WPILIB_DEPS_DIR` are what CI caches (see [`.fork/ci/README.md`](../ci/README.md)). Each has a `<lib>.stamp` beside it that records what made it: the URL, the tag and the patches for the download, plus the build arguments for the prefix. A dir whose stamp still matches is reused, and any change fetches or builds it again from scratch. The build tree, `build/<lib>`, isn't cached.

### Writing a recipe

1. Add `deps/<lib>.cmake`, modelled on `deps/double-conversion.cmake`:
   - fail if an upstream target it wires into doesn't exist, since upstream may have renamed it. Return early instead only when that target's module is switched off (e.g. `WPILIB_WITH_WPIMATH`);
   - call `wpilib_stock_add(<lib> GIT_REPOSITORY <url> PACKAGE <package> [CMAKE_ARGS ...])`, and turn off the library's tests and anything else WPILib doesn't need in `CMAKE_ARGS`;
   - call `wpilib_stock_thirdparty_include()` with the removed dir, and write any shims into it;
   - call `wpilib_stock_wire()` once for each upstream target that used the vendored copy;
   - defer the whole function with `cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL ...)`.
2. Add `.fork/patches/<lib>/` or a pin-table entry only if stock can't be used as-is.
3. Delete the library's line from the `TEMPORARY` block in [`.fork/manifest`](../manifest), and run `python3 .fork/sync.py prune`. Configure refuses to recreate a thirdparty dir that still holds the vendored copy.
4. Check that the build passes, that `cmake --install` works, and that the installed configs find the library (the `Check the installed configs` step in `fork-build.yml`; add the new target there).
5. A recipe or pin file outside `.fork/cmake/deps/`, `.fork/pin*` and `.fork/patches/` must be added to `KEY_INPUTS` in `.fork/ci/dep_cache.py`.

What breaks when upstream moves shows up in fork CI rather than as a merge conflict:
- a renamed target fails configure, through the recipe's target check;
- a changed config template fails configure, through the tripwire in `wpilib_stock_config_dependency()`;
- a moved thirdparty dir means the include path points nowhere, and the build fails.
