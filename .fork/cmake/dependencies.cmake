# The fork's dependency provider (#5, #12).
#
# Upstream's find_package calls stay unmodified; this provider answers them.
# CMake includes this file at the first project() call because it is listed in
# CMAKE_PROJECT_TOP_LEVEL_INCLUDES. The top-level CMakeLists.txt appends it (the
# fork's one-line modify surface). A consumer using the subdirectory route sets
# it themselves, since their project() runs before WPILib's CMakeLists.txt does.
#
# A recipe in deps/ answers find_package(<Package>) by defining a macro named
# _wpilib_provide_<Package>; anything else falls through to CMake's built-in
# search. The stock libraries upstream used to vendor need no answer: upstream
# never looked for them, so their recipes wire themselves in instead
# (stock.cmake, README.md).

include_guard(GLOBAL)

# The provider itself needs 3.24. The fork's floor is deliberately higher, and
# is enforced here so that upstream's cmake_minimum_required stays untouched.
if(CMAKE_VERSION VERSION_LESS 4.4)
    message(
        FATAL_ERROR
        "This fork of WPILib needs CMake 4.4 or newer (found ${CMAKE_VERSION})."
    )
endif()

# Where recipes keep what they fetch and install: sources under download/<dep>
# and install prefixes under prefix/<dep>. CI caches exactly those two subdirs
# (.fork/ci/dep-cache/), so a recipe must reuse a populated one rather than
# fetch or rebuild it, and must keep build trees elsewhere (such as build/).
set(WPILIB_DEPS_DIR
    "${CMAKE_BINARY_DIR}/_wpilib_deps"
    CACHE PATH
    "Where the dependency provider fetches, builds and installs dependencies."
)

# A macro rather than a function, so recipes can set result variables (such as
# OpenCV_INCLUDE_DIRS) in the scope of the find_package call. A recipe gets the
# find_package arguments after the package name, and answers by setting
# <package_name>_FOUND; leaving it unset hands the call back to find_package.
macro(wpilib_provide_dependency method package_name)
    if(COMMAND "_wpilib_provide_${package_name}")
        cmake_language(CALL "_wpilib_provide_${package_name}" ${ARGN})
    endif()
endmacro()

cmake_language(
    SET_DEPENDENCY_PROVIDER wpilib_provide_dependency
    SUPPORTED_METHODS FIND_PACKAGE
)

include("${CMAKE_CURRENT_LIST_DIR}/compile-workarounds.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/version.cmake")

# The recipes, one per dependency (#5, #12). Each either defines the
# _wpilib_provide_<Package> macro the dispatch above looks for, or, for a
# library upstream vendored and never looked for, defers its own wiring until
# upstream's targets exist.
include("${CMAKE_CURRENT_LIST_DIR}/stock.cmake")
file(GLOB _wpilib_recipes "${CMAKE_CURRENT_LIST_DIR}/deps/*.cmake")
foreach(_wpilib_recipe IN LISTS _wpilib_recipes)
    include("${_wpilib_recipe}")
endforeach()
