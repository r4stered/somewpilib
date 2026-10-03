# Fork CMake

| File | What it is |
|---|---|
| `dependencies.cmake` | The provider entry file. The top-level `CMakeLists.txt` includes it at `project()` (the fork's one-line modify surface), and it includes everything below. |
| `stock.cmake` | The vendor-nothing mechanism: the functions every recipe calls. |
| `stock-fetch.cmake` | The fetch step `stock.cmake` runs as `cmake -P`. |
| `deps/<lib>.cmake` | One recipe per dependency. `dependencies.cmake` includes every file here. |
| `compile-workarounds.cmake` | Per-source flags for carried code (#57). |
| `version.cmake` | Version stamping (#10). |

Tests for all of these live in [`.fork/tests/`](../tests): `python3 -m unittest discover -s .fork/tests`, which `fork-build.yml` also runs.

## Dependencies

Every dependency is built from **stock** source at configure time. The libraries upstream commits under `thirdparty/` are removed from the tree and fetched instead (#12, ADR 0002), and the external libraries upstream looks for are built rather than installed from a package manager (#5). No carried file is edited to make either work.

So there are two kinds of recipe:

| | What upstream does | What the recipe does | Reference |
|---|---|---|---|
| **Vendored** | Commits the source under `thirdparty/<lib>/` and compiles it into its own targets. Nothing calls `find_package` for it. | Fetches the library, stands in for the removed directory, and links the stock target into upstream's targets, from a deferred call. | `deps/double-conversion.cmake` |
| **External** | Calls `find_package(<Package>)`. | Defines a `_wpilib_provide_<Package>` macro, which the provider calls in place of that `find_package`. | `deps/opencv.cmake` |

Both fetch and build through `wpilib_stock_build()`, and both are named after the library, lower-cased: `deps/<lib>.cmake`. For a vendored library that is its `upstream_utils/<lib>.py` name.

### Answering a find_package call

`wpilib_provide_dependency()` in `dependencies.cmake` is the [dependency provider](https://cmake.org/cmake/help/latest/command/cmake_language.html#dependency-providers) CMake calls for every `find_package` in the build. It looks for a command named `_wpilib_provide_<Package>`, spelling `<Package>` exactly as the call does, and hands it the rest of that call's arguments. A recipe that defines one owns that package; every other call falls through to CMake's own search, untouched.

A recipe answers by setting `<Package>_FOUND`. It has to be a **macro**, not a function, so its result variables and imported targets land in the scope that called `find_package`: `cscore/CMakeLists.txt` reads `${OpenCV_INCLUDE_DIRS}`, and imported targets created in a function scope would be gone by the time upstream links them. Leaving `<Package>_FOUND` unset hands the call back to CMake, which is how `WPILIB_DEP_<DEP>_USE_SYSTEM` opts into an installed copy.

The provider also enforces the fork's CMake floor, so that upstream's `cmake_minimum_required` stays untouched.

### What happens at configure time

A vendored library's recipe registers a deferred call, which runs once the top-level directory is done, so upstream's targets exist. An external library's recipe runs during the `find_package` call it answers. Either way:

1. **Fetch and build.** `wpilib_stock_build()` clones the library at its tag, applies the fork's patches, and builds and installs it into `${WPILIB_DEPS_DIR}/prefix/<lib>`. It also installs that prefix alongside WPILib, since an installed WPILib config names the stock targets.
   - It builds static and position-independent, the way upstream compiled its vendored copy into WPILib's own libraries, with WPILib's compilers and build type.
   - Under a multi-config generator it builds only `CMAKE_BUILD_TYPE`, or Release. The Windows rows (#43) have to settle Debug.
   - It can't use `add_subdirectory` instead: CMake refuses to add subdirectories from a deferred call, and OpenCV makes a poor subproject in any case ([opencv#20548](https://github.com/opencv/opencv/issues/20548)).
2. **Import.** An external library's recipe calls `find_package(<Package> BYPASS_PROVIDER PATHS <prefix> NO_DEFAULT_PATH)` itself, so upstream's own call sees exactly what it expects. For a vendored library, `wpilib_stock_add()` does the same and then:
   1. **Stand in for the removed dir.** `wpilib_stock_thirdparty_include()` recreates `thirdparty/<lib>/include`, so upstream's include lists and `install(DIRECTORY)` still resolve. It is empty unless the recipe writes shims into it with `wpilib_stock_shim()`. The recreated dir holds a `.gitignore` of `*`, so git, `sync.py prune` and the invariants never see it.
   2. **Shim** (only if needed). A shim is a fork-owned header that maps upstream's renamed paths or namespaces onto stock. double-conversion's shims turn `wpi/double-conversion/*.h` into `<double-conversion/*.h>` and alias `wpi::double_conversion`.
   3. **Wire.** `wpilib_stock_wire(<module> <imported target> <package>)` links the stock target into upstream's target, and makes the generated `<module>-config.cmake` call `find_dependency(<package>)` before it imports `<module>`'s targets.

### Knobs

Each is `WPILIB_DEP_<LIB>_<knob>`, where `<LIB>` is the lib upper-cased with `-` turned into `_`, e.g. `WPILIB_DEP_DOUBLE_CONVERSION_GIT_TAG`.

| Knob | What it does |
|---|---|
| `_GIT_TAG` | The tag to fetch, overriding both defaults under *Which tag* below. |
| `_CMAKE_ARGS` | Extra arguments for the library's own build, appended after the recipe's so they win. |
| `_USE_SYSTEM` | Use an installed copy instead of building one. Only an external library has this: nothing looks for a vendored one, so there is no call to hand back. |

`-DFETCHCONTENT_SOURCE_DIR_<LIB>=<dir>` builds a local checkout instead. It is built unpatched, and rebuilt on every configure. Here `<LIB>` keeps its `-`, as FetchContent spells it.

### Which tag

The last one of these wins:

1. For a vendored library, the `tag = "..."` line in the carried `upstream_utils/<lib>.py`. This keeps the fork in lockstep with upstream's library bumps for free. An external library has no such script, so its recipe passes `DEFAULT_TAG` and owns the default itself.
2. The lib's entry in the **pin table**, [`.fork/pins.txt`](../pins.txt), used where the fork has to run ahead of upstream. Each entry records the upstream tag it overrides. Once upstream's `tag =` line changes, the entry is stale. The sync is to fail on a stale entry (#47), but nothing checks it yet. An external library is never in the table: there is no upstream tag for an entry to override, so its recipe is the pin.
3. `WPILIB_DEP_<LIB>_GIT_TAG` for one build.

Configure logs which one it used, e.g. `double-conversion: v3.4.0 (upstream_utils/double-conversion.py)` or `opencv: 4.13.0 (.fork/cmake/deps/opencv.cmake)`.

### Patches

`.fork/patches/<lib>/*.patch` are applied with `git apply`, in name order, after the fetch. Each one must have a line starting with `Exit condition:` above the diff, saying when it can be deleted. Configure fails on a patch without one. Once the condition holds, delete the patch.

### Caching

`download/<lib>` and `prefix/<lib>` under `WPILIB_DEPS_DIR` are what CI caches (see [`.fork/ci/README.md`](../ci/README.md)). Each has a `<lib>.stamp` beside it that records what made it: the URL, the tag and the patches for the download, plus the build arguments for the prefix. A dir whose stamp still matches is reused, and any change fetches or builds it again from scratch. The build tree, `build/<lib>`, isn't cached.

### Writing a recipe

Add `deps/<lib>.cmake`, modelled on `deps/double-conversion.cmake` for a vendored library or `deps/opencv.cmake` for an external one. Turn off the library's tests and anything else WPILib doesn't need in `CMAKE_ARGS`. Then:

**A vendored library**

1. Fail if an upstream target the recipe wires into doesn't exist, since upstream may have renamed it. Return early instead only when that target's module is switched off (e.g. `WPILIB_WITH_WPIMATH`).
2. Call `wpilib_stock_add(<lib> GIT_REPOSITORY <url> PACKAGE <package> [CMAKE_ARGS ...])`.
3. Call `wpilib_stock_thirdparty_include()` with the removed dir, and write any shims into it.
4. Call `wpilib_stock_wire()` once for each upstream target that used the vendored copy.
5. Defer the whole function with `cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL ...)`.
6. Delete the library's line from the `TEMPORARY` block in [`.fork/manifest`](../manifest), and run `python3 .fork/sync.py prune`. Configure refuses to recreate a thirdparty dir that still holds the vendored copy.

**An external library**

1. Define `macro(_wpilib_provide_<Package>)`, spelling `<Package>` as upstream's `find_package` call does.
2. Return without setting `<Package>_FOUND` when `WPILIB_DEP_<LIB>_USE_SYSTEM` is on.
3. Otherwise call `wpilib_stock_build(<lib> <prefix_var> GIT_REPOSITORY <url> DEFAULT_TAG <tag> [CMAKE_ARGS ...])`, guarded so that repeated `find_package` calls build and install it once, and then `find_package(<Package> ${ARGN} CONFIG BYPASS_PROVIDER PATHS <prefix> NO_DEFAULT_PATH)`.

**Either way**

1. Add `.fork/patches/<lib>/` or a pin-table entry only if stock can't be used as-is.
2. Check that the build passes, that `cmake --install` works, and that the installed configs find the library (the `Check the installed configs find their dependencies` step in `fork-build.yml`; add the new library there).
3. A recipe or pin file outside `.fork/cmake/deps/`, `.fork/pin*` and `.fork/patches/` must be added to `KEY_INPUTS` in `.fork/ci/dep_cache.py`.

What breaks when upstream moves shows up in fork CI rather than as a merge conflict:
- a renamed target fails configure, through the recipe's target check;
- a changed config template fails configure, through the tripwire in `wpilib_stock_config_dependency()`;
- a moved thirdparty dir means the include path points nowhere, and the build fails;
- a renamed package in a `find_package` call stops matching its recipe's macro, and the call falls through to a search that finds nothing.
