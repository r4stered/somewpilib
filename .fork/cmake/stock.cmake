# Stock libraries: the vendor-nothing mechanism (#12, ADR 0002).
#
# Upstream commits its third-party libraries under thirdparty/. The fork
# removes them (.fork/manifest) and fetches each one stock instead. A recipe in
# .fork/cmake/deps/<lib>.cmake uses the functions below to fetch the library,
# stand in for the removed dir and wire the stock target into upstream's
# targets, all without editing a carried file. .fork/cmake/README.md walks
# through writing one.
#
# The functions that don't need a project (tag, patches, thirdparty dir, shim,
# config dependency) are tested by .fork/tests/test_stock.py.

include_guard(GLOBAL)

# Functions keep the policies in force where they're defined, so these hold
# whatever upstream's cmake_minimum_required says.
cmake_policy(PUSH)
cmake_policy(VERSION 3.30...4.4)

# Sets <tag_var> to the git tag to fetch <lib> at, and <source_var> to where it
# came from.
#
#   wpilib_stock_tag(<lib> <tag_var> <source_var> [DEFAULT <tag>])
#
# Last one wins:
#   1. the `tag = "..."` line in the carried upstream_utils/<lib>.py, then the
#      lib's entry in the pin table, .fork/pins.txt -- or, with a non-empty
#      DEFAULT, <tag> instead of both. A dependency upstream doesn't vendor has
#      no upstream_utils script to read and no upstream tag for a pin entry to
#      override, so its recipe owns the default. An empty DEFAULT is no
#      default, so a caller can pass one through unconditionally;
#   2. -DWPILIB_DEP_<LIB>_GIT_TAG=..., where <LIB> is <lib> upper-cased with
#      each - turned into _.
function(wpilib_stock_tag lib tag_var source_var)
    cmake_parse_arguments(PARSE_ARGV 3 arg "" "DEFAULT" "")
    if(arg_DEFAULT)
        set(tag "${arg_DEFAULT}")
        set(source ".fork/cmake/deps/${lib}.cmake")
    else()
        _wpilib_stock_upstream_tag(${lib} tag source)
    endif()

    _wpilib_stock_knob(${lib} GIT_TAG knob)
    if(NOT "${${knob}}" STREQUAL "")
        set(tag "${${knob}}")
        set(source "-D${knob}")
    endif()

    set(${tag_var} "${tag}" PARENT_SCOPE)
    set(${source_var} "${source}" PARENT_SCOPE)
endfunction()

# Sets <tag_var> and <source_var> from upstream's own pin, upstream_utils/<lib>.py,
# and then from the fork's pin table over it.
function(_wpilib_stock_upstream_tag lib tag_var source_var)
    get_filename_component(root "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../.." ABSOLUTE)

    set(script "upstream_utils/${lib}.py")
    if(NOT EXISTS "${root}/${script}")
        message(
            FATAL_ERROR
            "stock ${lib}: ${script} is missing, and the default tag comes from it."
        )
    endif()
    file(STRINGS "${root}/${script}" lines REGEX "^[ \t]*tag = [\"'][^\"']+[\"']")
    list(LENGTH lines count)
    if(NOT count EQUAL 1)
        message(
            FATAL_ERROR
            "stock ${lib}: expected one `tag = \"...\"` line in ${script}, found ${count}."
        )
    endif()
    string(REGEX REPLACE "^[ \t]*tag = [\"']([^\"']+)[\"'].*" "\\1" tag "${lines}")
    set(source "${script}")

    # The pin table: `<lib> <tag> <upstream tag it overrides>` per line. The
    # third field is what lets the sync spot a stale pin, once it checks (#47).
    set(pins "${root}/.fork/pins.txt")
    if(EXISTS "${pins}")
        file(STRINGS "${pins}" lines)
        set(pinned FALSE)
        foreach(line IN LISTS lines)
            string(REGEX REPLACE "#.*" "" line "${line}")
            string(STRIP "${line}" line)
            if(line STREQUAL "")
                continue()
            endif()
            separate_arguments(fields UNIX_COMMAND "${line}")
            list(LENGTH fields count)
            if(NOT count EQUAL 3)
                message(
                    FATAL_ERROR
                    "stock: .fork/pins.txt entry `${line}` isn't "
                    "`<lib> <tag> <upstream tag it overrides>`."
                )
            endif()
            list(GET fields 0 pin_lib)
            if(NOT pin_lib STREQUAL lib)
                continue()
            endif()
            if(pinned)
                message(FATAL_ERROR "stock ${lib}: .fork/pins.txt lists it more than once.")
            endif()
            set(pinned TRUE)
            list(GET fields 1 tag)
            list(GET fields 2 overridden)
            set(source ".fork/pins.txt, over upstream's ${overridden}")
        endforeach()
    endif()

    set(${tag_var} "${tag}" PARENT_SCOPE)
    set(${source_var} "${source}" PARENT_SCOPE)
endfunction()

# Sets <knob_var> to the name of one of <lib>'s knobs, WPILIB_DEP_<LIB>_<suffix>.
function(_wpilib_stock_knob lib suffix knob_var)
    string(TOUPPER "${lib}" uc)
    string(REPLACE "-" "_" knob "WPILIB_DEP_${uc}_${suffix}")
    set(${knob_var} "${knob}" PARENT_SCOPE)
endfunction()

# Sets <patches_var> to the fork's patches for <lib>, .fork/patches/<lib>/*.patch
# in name order, and <digest_var> to a hash of their names and contents. Every
# patch must say when it can be deleted, on a line starting `Exit condition:`
# above the diff.
function(wpilib_stock_patches lib patches_var digest_var)
    get_filename_component(root "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../.." ABSOLUTE)
    file(GLOB patches "${root}/.fork/patches/${lib}/*.patch")
    list(SORT patches)
    set(digest "")
    foreach(patch IN LISTS patches)
        file(STRINGS "${patch}" exit_condition REGEX "^Exit condition: " LIMIT_COUNT 1)
        cmake_path(GET patch FILENAME name)
        if(NOT exit_condition)
            message(
                FATAL_ERROR
                "stock ${lib}: .fork/patches/${lib}/${name} has no "
                "`Exit condition: ...` line saying when it can be deleted."
            )
        endif()
        file(SHA256 "${patch}" hash)
        string(APPEND digest "${name}=${hash};")
    endforeach()
    string(SHA256 digest "${digest}")
    set(${patches_var} "${patches}" PARENT_SCOPE)
    set(${digest_var} "${digest}" PARENT_SCOPE)
endfunction()

# Fetches <lib> stock, patches it, builds it and installs it into
# ${WPILIB_DEPS_DIR}/prefix/<lib> at configure time, adds an install rule that
# copies that prefix into WPILib's own, and sets <prefix_var> to it.
#
#   wpilib_stock_build(<lib> <prefix_var> GIT_REPOSITORY <url>
#                       [DEFAULT_TAG <tag>] [CMAKE_ARGS <arg>...])
#
# The tag comes from wpilib_stock_tag(), with DEFAULT_TAG passed on as its
# DEFAULT, and the patches from wpilib_stock_patches(). It builds static and
# position-independent, the way upstream compiled its vendored copy into
# WPILib's own libraries, with WPILib's compilers and build type. CMAKE_ARGS
# adds the library's own options, and -DWPILIB_DEP_<LIB>_CMAKE_ARGS=... is
# appended after them, so a build can extend or override any of them. Under a
# multi-config generator it builds only CMAKE_BUILD_TYPE, or Release; the
# Windows rows (#43) have to settle how a Debug build gets a matching runtime.
#
# download/<lib> and prefix/<lib> are what CI caches, so each gets a
# <lib>.stamp beside it recording what made it, and one whose stamp still
# matches is reused rather than fetched or built again. The build tree,
# build/<lib>, isn't cached. -DFETCHCONTENT_SOURCE_DIR_<LIB>=<dir>
# (FetchContent's own override, <LIB> upper-cased) builds a local checkout
# instead, unpatched and on every configure.
function(wpilib_stock_build lib prefix_var)
    cmake_parse_arguments(
        PARSE_ARGV 2 arg
        ""
        "GIT_REPOSITORY;DEFAULT_TAG"
        "CMAKE_ARGS"
    )
    if(NOT arg_GIT_REPOSITORY)
        message(FATAL_ERROR "wpilib_stock_build(${lib}): GIT_REPOSITORY is required.")
    endif()
    string(TOUPPER "${lib}" uc)
    set(local_checkout "${FETCHCONTENT_SOURCE_DIR_${uc}}")

    _wpilib_stock_knob(${lib} GIT_TAG tag_knob)
    set(${tag_knob}
        ""
        CACHE STRING
        "Git tag to fetch ${lib} at, overriding upstream_utils and the pin table."
    )
    _wpilib_stock_knob(${lib} CMAKE_ARGS args_knob)
    set(${args_knob}
        ""
        CACHE STRING
        "Extra CMake arguments for ${lib}'s build, appended to the recipe's."
    )

    if(local_checkout)
        set(src "${local_checkout}")
        set(fetched "${src}, unpatched, from FETCHCONTENT_SOURCE_DIR_${uc}")
        message(STATUS "${lib}: ${fetched}")
    else()
        wpilib_stock_tag(${lib} tag source DEFAULT "${arg_DEFAULT_TAG}")
        wpilib_stock_patches(${lib} patches digest)
        set(src "${WPILIB_DEPS_DIR}/download/${lib}")
        set(fetched "${arg_GIT_REPOSITORY} ${tag} ${digest}")
        _wpilib_stock_stamped("${src}" "${fetched}" fresh)
        if(fresh)
            message(STATUS "${lib}: ${tag} (${source}), already downloaded")
        else()
            message(STATUS "${lib}: ${tag} (${source}), fetching")
            _wpilib_stock_fetch(${lib} "${arg_GIT_REPOSITORY}" "${tag}" "${patches}")
            file(WRITE "${src}.stamp" "${fetched}\n")
        endif()
    endif()

    set(config "${CMAKE_BUILD_TYPE}")
    if(NOT config)
        set(config Release)
    endif()
    set(configure_args
        -G "${CMAKE_GENERATOR}"
        -DCMAKE_BUILD_TYPE=${config}
        -DBUILD_SHARED_LIBS=OFF
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
        # CMake 4 refuses a cmake_minimum_required below 3.5, which older
        # tags (such as a -DWPILIB_DEP_*_GIT_TAG downgrade) still have.
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    )
    if(CMAKE_GENERATOR_PLATFORM)
        list(APPEND configure_args -A "${CMAKE_GENERATOR_PLATFORM}")
    endif()
    if(CMAKE_GENERATOR_TOOLSET)
        list(APPEND configure_args -T "${CMAKE_GENERATOR_TOOLSET}")
    endif()
    _wpilib_stock_forward(configure_args
        CMAKE_MAKE_PROGRAM
        CMAKE_TOOLCHAIN_FILE
        CMAKE_C_COMPILER
        CMAKE_CXX_COMPILER
        CMAKE_MSVC_RUNTIME_LIBRARY
        CMAKE_OSX_ARCHITECTURES
        CMAKE_OSX_DEPLOYMENT_TARGET
    )
    list(APPEND configure_args ${arg_CMAKE_ARGS} ${${args_knob}})
    set(prefix "${WPILIB_DEPS_DIR}/prefix/${lib}")
    # The mechanism is in the stamp too, as it is in CI's dep-cache key.
    file(SHA256 "${CMAKE_CURRENT_FUNCTION_LIST_FILE}" mechanism)
    string(SHA256 built "${fetched};${configure_args};${mechanism}")
    # A launcher (sccache) doesn't change what's built, so it stays out of the
    # stamp, and a prefix built with one is reused without.
    _wpilib_stock_forward(configure_args CMAKE_C_COMPILER_LAUNCHER CMAKE_CXX_COMPILER_LAUNCHER)

    _wpilib_stock_stamped("${prefix}" "${built}" fresh)
    if(fresh AND NOT local_checkout)
        message(STATUS "${lib}: already built")
    else()
        message(STATUS "${lib}: building")
        set(build "${WPILIB_DEPS_DIR}/build/${lib}")
        file(REMOVE_RECURSE "${prefix}" "${prefix}.stamp")
        # A local checkout rebuilds incrementally; anything else starts clean,
        # since the source or the compilers may have changed under the tree.
        if(NOT local_checkout)
            file(REMOVE_RECURSE "${build}")
        endif()
        _wpilib_stock_run(${lib} configure
            "${CMAKE_COMMAND}" -S "${src}" -B "${build}" ${configure_args}
        )
        _wpilib_stock_run(${lib} build
            "${CMAKE_COMMAND}" --build "${build}" --config ${config} --parallel
        )
        _wpilib_stock_run(${lib} install
            "${CMAKE_COMMAND}" --install "${build}" --config ${config} --prefix "${prefix}"
        )
        file(WRITE "${prefix}.stamp" "${built}\n")
    endif()

    # Alongside WPILib, because an installed WPILib config names its targets.
    # The rule belongs to whichever directory scope asked for the build first,
    # which doesn't matter: DESTINATION is the install prefix either way, and
    # every directory's install script runs.
    install(DIRECTORY "${prefix}/" DESTINATION . USE_SOURCE_PERMISSIONS)
    set(${prefix_var} "${prefix}" PARENT_SCOPE)
endfunction()

# Builds <lib> with wpilib_stock_build(), then imports it with
# find_package(<package> CONFIG) as GLOBAL targets. Sets <lib>_PREFIX to the
# prefix. This is what a recipe for a library upstream vendored calls: no
# carried file looks for such a library, so the provider has no find_package
# call to answer and the recipe does the import itself.
#
#   wpilib_stock_add(<lib> GIT_REPOSITORY <url> PACKAGE <package>
#                    [CMAKE_ARGS <arg>...])
function(wpilib_stock_add lib)
    cmake_parse_arguments(PARSE_ARGV 1 arg "" "GIT_REPOSITORY;PACKAGE" "CMAKE_ARGS")
    if(NOT arg_GIT_REPOSITORY OR NOT arg_PACKAGE)
        message(
            FATAL_ERROR
            "wpilib_stock_add(${lib}): GIT_REPOSITORY and PACKAGE are required."
        )
    endif()

    wpilib_stock_build(${lib} prefix
        GIT_REPOSITORY "${arg_GIT_REPOSITORY}"
        CMAKE_ARGS ${arg_CMAKE_ARGS}
    )
    # BYPASS_PROVIDER: the provider's own recipes must never answer each other.
    find_package(
        ${arg_PACKAGE}
        CONFIG
        REQUIRED
        GLOBAL
        BYPASS_PROVIDER
        PATHS "${prefix}"
        NO_DEFAULT_PATH
    )
    set(${lib}_PREFIX "${prefix}" PARENT_SCOPE)
endfunction()

# Appends -D<var>=<value> to <list_var> for each of the variables named after
# it that is set. A list value stays one argument.
function(_wpilib_stock_forward list_var)
    set(args "${${list_var}}")
    foreach(var IN LISTS ARGN)
        if(${var})
            string(REPLACE ";" "\\;" value "${${var}}")
            list(APPEND args "-D${var}=${value}")
        endif()
    endforeach()
    set(${list_var} "${args}" PARENT_SCOPE)
endfunction()

# Sets <fresh_var> to whether <dir> exists and <dir>.stamp records <what>.
function(_wpilib_stock_stamped dir what fresh_var)
    set(have "")
    if(EXISTS "${dir}.stamp")
        file(READ "${dir}.stamp" have)
    endif()
    if(IS_DIRECTORY "${dir}" AND have STREQUAL "${what}\n")
        set(${fresh_var} TRUE PARENT_SCOPE)
    else()
        set(${fresh_var} FALSE PARENT_SCOPE)
    endif()
endfunction()

# Clones <url> at <tag> into download/<lib> and applies <patches>, through
# stock-fetch.cmake.
function(_wpilib_stock_fetch lib url tag patches)
    set(src "${WPILIB_DEPS_DIR}/download/${lib}")
    set(work "${WPILIB_DEPS_DIR}/fetch/${lib}")
    file(REMOVE_RECURSE "${src}" "${src}.stamp" "${work}")

    find_program(WPILIB_GIT_EXECUTABLE git REQUIRED)
    # A shallow clone can only reach a tag or branch, not a bare commit.
    set(shallow TRUE)
    string(LENGTH "${tag}" tag_length)
    if(tag MATCHES "^[0-9a-f]+$" AND tag_length GREATER_EQUAL 7)
        set(shallow FALSE)
    endif()

    string(TOLOWER "${lib}" lc)
    _wpilib_stock_run(${lib} fetch
        "${CMAKE_COMMAND}"
        "-DNAME=${lc}"
        "-DGIT_REPOSITORY=${url}"
        "-DGIT_TAG=${tag}"
        "-DGIT_SHALLOW=${shallow}"
        "-DSOURCE_DIR=${src}"
        "-DWORK_DIR=${work}"
        "-DGIT_EXECUTABLE=${WPILIB_GIT_EXECUTABLE}"
        "-DPATCHES=${patches}"
        -P "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/stock-fetch.cmake"
    )
endfunction()

# Runs a sub-build step, and fails configure with its output if it fails.
function(_wpilib_stock_run lib step)
    execute_process(
        COMMAND ${ARGN}
        RESULT_VARIABLE result
        OUTPUT_VARIABLE output
        ERROR_VARIABLE output
    )
    if(NOT result EQUAL 0)
        message(FATAL_ERROR "stock ${lib}: ${step} failed (${result}):\n${output}")
    endif()
endfunction()

# Stands in for a removed thirdparty/<lib> dir, <dir>, so upstream's include
# lists and install(DIRECTORY) of <dir>/include still resolve. Creates
# <dir>/include, empty until wpilib_stock_shim() writes into it, and sets
# <include_var> to it. <dir> gets a .gitignore that ignores everything, so git,
# prune and the invariants never see it.
function(wpilib_stock_thirdparty_include dir include_var)
    set(marker "${dir}/.gitignore")
    if(IS_DIRECTORY "${dir}" AND NOT EXISTS "${marker}")
        file(GLOB_RECURSE leftovers LIST_DIRECTORIES false "${dir}/*")
        if(leftovers)
            message(
                FATAL_ERROR
                "stock: ${dir} still holds the vendored copy. Delete its temporary "
                "negation from .fork/manifest and run .fork/sync.py prune."
            )
        endif()
    endif()
    file(MAKE_DIRECTORY "${dir}/include")
    if(NOT EXISTS "${marker}")
        file(
            WRITE "${marker}"
            "# Generated by .fork/cmake/stock.cmake; the fork doesn't carry this dir.\n*\n"
        )
    endif()
    set(${include_var} "${dir}/include" PARENT_SCOPE)
endfunction()

# Writes <content> to <path> unless it already holds exactly that, so an
# unchanged shim doesn't rebuild everything that includes it.
function(wpilib_stock_shim path content)
    if(EXISTS "${path}")
        file(READ "${path}" old)
        if(old STREQUAL content)
            return()
        endif()
    endif()
    file(WRITE "${path}" "${content}")
endfunction()

# Makes the generated <module>-config.cmake at <config> find <package> before it
# imports <module>'s targets, which reference the stock ones. HINTS puts the
# config's own install prefix first. Does nothing if the line is already there.
function(wpilib_stock_config_dependency config module package)
    file(READ "${config}" text)
    set(line "find_dependency(${package} HINTS \"\${SELF_DIR}/../..\")")
    string(FIND "${text}" "${line}" found)
    if(found GREATER -1)
        return()
    endif()
    set(anchor "include(\${SELF_DIR}/${module}.cmake)")
    string(FIND "${text}" "${anchor}" found)
    if(found EQUAL -1)
        # Tripwire: upstream changed its config template.
        message(
            FATAL_ERROR
            "stock: ${config} no longer has `${anchor}`, so ${package} can't be "
            "added before it. Update wpilib_stock_config_dependency()."
        )
    endif()
    string(REPLACE "${anchor}" "${line}\n${anchor}" text "${text}")
    file(WRITE "${config}" "${text}")
endfunction()

# Wires the stock <target> into upstream's <module> target: links it, with the
# plain signature upstream's target_link_libraries use (CMake won't mix the two
# on one target), and makes the installed <module>-config.cmake find <package>,
# since <module>'s exported link interface names <target>.
function(wpilib_stock_wire module target package)
    get_filename_component(root "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../.." ABSOLUTE)
    # WPILib's binary dir, where its configs are generated. Read from WPILib's
    # directory, since a subdirectory consumer's scope doesn't have it.
    get_directory_property(bin DIRECTORY "${root}" DEFINITION WPILIB_BINARY_DIR)

    target_link_libraries(${module} ${target})
    wpilib_stock_config_dependency("${bin}/${module}-config.cmake" ${module} ${package})
endfunction()

cmake_policy(POP)
