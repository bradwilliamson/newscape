# 3.26: compile_commands.json records each object's "output", which the
# header-selection test and tools/warning_baseline.py rely on.
cmake_minimum_required(VERSION 3.26)

# Generated files belong in out/<preset>/. Inside the source tree, a build
# directory anywhere else is refused: that covers the source root and the
# historical build/ directory (Netscape's build_number, genrc.sh, ...), which
# must never receive build output. Build directories outside the source tree
# (e.g. a parent project using add_subdirectory()) are fine. Check before
# project() so a refused configure does not run compiler probes. CMake itself
# may still have written CMakeCache.txt and CMakeFiles/ by this point.
file(REAL_PATH "${CMAKE_CURRENT_SOURCE_DIR}" _newscape_src)
file(REAL_PATH "${CMAKE_CURRENT_BINARY_DIR}" _newscape_bin)
string(FIND "${_newscape_bin}/" "${_newscape_src}/" _newscape_in_src)
string(FIND "${_newscape_bin}" "${_newscape_src}/out/" _newscape_in_out)
if(_newscape_in_src EQUAL 0 AND NOT _newscape_in_out EQUAL 0)
  message(FATAL_ERROR
    "Refusing to build in ${CMAKE_CURRENT_BINARY_DIR}: inside the source tree, "
    "build directories must be under out/. Use a preset, which builds in "
    "out/<preset>/, e.g. `cmake --workflow --preset gcc-debug`. Remove any "
    "CMakeCache.txt and CMakeFiles/ this attempt left behind.")
endif()

project(newscape
  DESCRIPTION "Reviving the June 1998 Mozilla Classic source on modern systems"
  LANGUAGES C)

# tools/warning_baseline.py and the header-selection test read compile_commands.json.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}/bin")
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}/lib")

list(APPEND CMAKE_MODULE_PATH "${PROJECT_SOURCE_DIR}/cmake")
include(NewscapeTargets)

include("${PROJECT_SOURCE_DIR}/cmake/components/jsref.cmake")

if(PROJECT_IS_TOP_LEVEL)
  enable_testing()
  add_subdirectory(tests/jsref)
  add_subdirectory(tests/tools)
endif()
