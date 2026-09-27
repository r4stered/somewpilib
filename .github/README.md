# somewpilib

A CMake-only C++ fork of [WPILib](https://github.com/wpilibsuite/allwpilib) for desktop use: Linux, Windows and macOS. There's no Java, no Gradle or Bazel, and no roboRIO or SystemCore target.

The fork tracks upstream's `main` through a weekly sync. It removes whatever it doesn't build and edits one line of upstream's code. Everything else the fork owns lives in [`.fork/`](../.fork) and in the `fork-*` workflows. The root [README](../README.md) is upstream's and is left untouched, so parts of it don't apply here.

## Requirements

- CMake 4.4 or newer. Upstream's `cmake_minimum_required` is lower, but the fork's dependency provider enforces 4.4.
- A C++23 compiler: GCC 14 or newer, Clang, AppleClang or MSVC.
- Network access at configure time.

## Building

```bash
cmake --preset default -DCMAKE_BUILD_TYPE=Release
cmake --build build-cmake
```

Dependencies are provided by the fork's **dependency provider**, [`.fork/cmake/dependencies.cmake`](../.fork/cmake/dependencies.cmake). It answers upstream's `find_package` calls without changing them. For now it passes every call through, so dependencies such as OpenCV still have to be installed on the system.

## Using it from your own project

There are two supported routes.

### Installed

Build and install WPILib, then point your project at the prefix:

```bash
cmake --install build-cmake --prefix /path/to/prefix
```

```cmake
find_package(wpilib REQUIRED)
```

Configure your project with `-DCMAKE_PREFIX_PATH=/path/to/prefix`.

### Subdirectory

Add the fork as a git submodule and `add_subdirectory` it. Your project's `project()` runs before WPILib's `CMakeLists.txt` does, so the provider can't switch itself on. Opt in by listing it in `CMAKE_PROJECT_TOP_LEVEL_INCLUDES` when you configure your project:

```bash
cmake -B build -DCMAKE_PROJECT_TOP_LEVEL_INCLUDES=path/to/somewpilib/.fork/cmake/dependencies.cmake
```

You can also set it in your preset's `cacheVariables`. That file is the only entry point. The provider answers only the dependencies it knows, and passes your project's other `find_package` calls through untouched.

Plain `FetchContent` isn't supported, because the source doesn't exist yet when the provider would have to be set.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
