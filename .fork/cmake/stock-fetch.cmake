# Fetches one stock library: cmake -P, run by wpilib_stock_add() in stock.cmake.
#
# Script mode keeps FetchContent's stamps under FETCHCONTENT_BASE_DIR, so the
# caller can reset a fetch by deleting SOURCE_DIR and WORK_DIR. (In a project,
# FetchContent keeps them under CMakeFiles/ and would try to update a source
# dir that is gone.)
#
# Takes -D: NAME, GIT_EXECUTABLE, GIT_REPOSITORY, GIT_TAG, GIT_SHALLOW,
# SOURCE_DIR, WORK_DIR, and optionally PATCHES (a list, applied with git apply).

cmake_minimum_required(VERSION 4.4)

set(patch_command "")
if(PATCHES)
    set(patch_command
        PATCH_COMMAND
        "${GIT_EXECUTABLE}"
        apply
        --whitespace=nowarn
        ${PATCHES}
    )
endif()

set(FETCHCONTENT_BASE_DIR "${WORK_DIR}")
include(FetchContent)
FetchContent_Populate(
    ${NAME}
    QUIET
    GIT_REPOSITORY "${GIT_REPOSITORY}"
    GIT_TAG "${GIT_TAG}"
    GIT_SHALLOW ${GIT_SHALLOW}
    SOURCE_DIR "${SOURCE_DIR}"
    BINARY_DIR "${WORK_DIR}/build"
    ${patch_command}
)
