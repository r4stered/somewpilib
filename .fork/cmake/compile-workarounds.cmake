# Per-source compile workarounds for carried upstream code (#57).
#
# Each one is set from here, after the targets exist, so no carried file is
# edited. Each has an exit condition; remove it once that holds.

include_guard(GLOBAL)

function(_wpilib_compile_workarounds)
    if(NOT TARGET wpiutil)
        return()
    endif()
    get_target_property(wpiutil_dir wpiutil SOURCE_DIR)

    # upb's utf8_range: its SSE4.1 path passes 0x80-0xFF to _mm_setr_epi8, whose
    # parameters are char, and GCC's -pedantic turns that into -Werror=overflow.
    # The path is compiled whenever __SSE4_1__ is defined, as it is by default on
    # the ubuntu-26.04 runners (amd64v3) and with -march=native on any
    # x86-64-v2 or newer machine.
    # Exit condition: protobuf casts those constants (unfixed as of v36.2 and
    # main on 2026-09-27).
    set(utf8_range "${wpiutil_dir}/src/main/native/thirdparty/upb/src/utf8_range.c")
    if(NOT EXISTS "${utf8_range}")
        # Tripwire: upb moved (e.g. went stock), so re-home this workaround.
        message(FATAL_ERROR "compile-workarounds.cmake: ${utf8_range} is gone")
    endif()
    set_source_files_properties(
        "${utf8_range}"
        TARGET_DIRECTORY wpiutil
        PROPERTIES COMPILE_OPTIONS "$<$<C_COMPILER_ID:GNU>:-Wno-overflow>"
    )
endfunction()

# Runs once the including project's top-level directory is fully processed, so
# every WPILib target exists by then.
cmake_language(
    DEFER DIRECTORY "${CMAKE_SOURCE_DIR}"
    CALL _wpilib_compile_workarounds
)
