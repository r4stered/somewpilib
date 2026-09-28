# Version stamping (#10).
#
# The carried configure_file(...WPILibVersion.cpp.in...) calls in wpilibc and
# the tools expand ${wpilib_version}, which only Gradle and Bazel ever set. This
# sets it from git describe, run in the fork's own checkout, so builds report
# e.g. 2027.0.0-alpha-7-66-gae53888dd. A hand-passed -Dwpilib_version=... wins.
#
# git describe runs at configure time only, so an incremental build reports a
# stale string until it reconfigures. CI configures fresh, so CI is exact.

include_guard(GLOBAL)

get_filename_component(_wpilib_fork_root "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)

# Runs git in the fork's checkout; sets <result_var> and _git_result.
macro(_wpilib_git result_var)
    execute_process(
        COMMAND "${WPILIB_GIT_EXECUTABLE}" ${ARGN}
        WORKING_DIRECTORY "${_wpilib_fork_root}"
        RESULT_VARIABLE _git_result
        OUTPUT_VARIABLE ${result_var}
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
endmacro()

# Sets <version_var> to git describe's version, or leaves it unset and sets
# <reason_var> to why it can't.
function(_wpilib_describe version_var reason_var)
    # find_program rather than find_package(Git), which would go through the
    # dependency provider before it's set.
    find_program(WPILIB_GIT_EXECUTABLE git)
    if(NOT WPILIB_GIT_EXECUTABLE)
        set(${reason_var} "git not found" PARENT_SCOPE)
        return()
    endif()

    # A fork copy without its own .git (say, vendored in a consumer's repo)
    # must not describe the enclosing repo.
    _wpilib_git(toplevel rev-parse --show-toplevel)
    if(NOT _git_result EQUAL 0)
        set(${reason_var} "not a git checkout" PARENT_SCOPE)
        return()
    endif()
    file(REAL_PATH "${toplevel}" toplevel)
    file(REAL_PATH "${_wpilib_fork_root}" fork_root)
    if(NOT toplevel STREQUAL fork_root)
        set(${reason_var} "not a git checkout of its own" PARENT_SCOPE)
        return()
    endif()

    # A shallow clone's describe counts commits from the wrong base.
    _wpilib_git(shallow rev-parse --is-shallow-repository)
    if(shallow STREQUAL "true")
        set(${reason_var} "shallow clone" PARENT_SCOPE)
        return()
    endif()

    _wpilib_git(described describe --tags --match "v[0-9]*")
    if(NOT _git_result EQUAL 0)
        set(${reason_var} "no v* tags" PARENT_SCOPE)
        return()
    endif()
    string(REGEX REPLACE "^v" "" described "${described}")
    set(${version_var} "${described}" PARENT_SCOPE)
endfunction()

if(NOT DEFINED wpilib_version)
    _wpilib_describe(wpilib_version _wpilib_version_failure)
    if(NOT DEFINED wpilib_version)
        set(wpilib_version "0.0.0-unknown")
        message(
            WARNING
            "WPILib version: ${_wpilib_version_failure}, so builds report "
            "${wpilib_version}. Build from a full git clone with the v* tags, "
            "or pass -Dwpilib_version=..."
        )
    endif()
endif()
message(STATUS "WPILib version: ${wpilib_version}")

# The aggregate wpilib package gets a version file, so consumers can write
# find_package(wpilib 2027). Per-module configs stay version-less.
function(_wpilib_write_version_file)
    if(wpilib_version MATCHES "^([0-9]+\\.[0-9]+\\.[0-9]+)")
        set(core "${CMAKE_MATCH_1}")
    else()
        set(core "0.0.0")
        message(
            WARNING
            "WPILib version ${wpilib_version} has no X.Y.Z core, so the wpilib "
            "package reports version ${core}."
        )
    endif()
    include(CMakePackageConfigHelpers)
    write_basic_package_version_file(
        "${CMAKE_BINARY_DIR}/wpilib-config-version.cmake"
        VERSION "${core}"
        COMPATIBILITY SameMajorVersion
    )
    install(
        FILES "${CMAKE_BINARY_DIR}/wpilib-config-version.cmake"
        DESTINATION share/wpilib
    )
endfunction()

# Only when the fork is the top-level project, so a subdirectory consumer's
# install is left alone. Deferred to the end of the top-level directory, since
# languages aren't enabled yet when this file runs and the version file checks
# CMAKE_SIZEOF_VOID_P.
file(REAL_PATH "${_wpilib_fork_root}" _wpilib_fork_real)
file(REAL_PATH "${CMAKE_SOURCE_DIR}" _wpilib_source_real)
if(_wpilib_fork_real STREQUAL _wpilib_source_real)
    cmake_language(
        DEFER DIRECTORY "${CMAKE_SOURCE_DIR}"
        CALL _wpilib_write_version_file
    )
endif()
