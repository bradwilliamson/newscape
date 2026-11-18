# Checkpoint tests for js/ref:
#   - archive scripts run through the shell, checking exit status, stderr and
#     the exact stdout;
#   - the generated CPU configuration matches the compiler's ABI;
#   - a program that only links the jsref target can embed the engine;
#   - each include site, and every object file, selected the generated
#     prcpucfg.h according to the compiler's dependency output.

set(_sanitizer_env "")
if(NEWSCAPE_SANITIZERS)
  set(_sanitizer_env
    "ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:abort_on_error=0"
    "UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1")
endif()

# jsref_script_test(<name> <script in js/ref> <expected stdout file>
#                   [REQUIRE <exact line>...])
function(jsref_script_test name script expected)
  cmake_parse_arguments(PARSE_ARGV 3 _arg "" "" "REQUIRE")
  list(JOIN _arg_REQUIRE "|" _required)
  add_test(NAME jsref.script.${name}
    COMMAND "${CMAKE_COMMAND}"
            "-DJS_SHELL=$<TARGET_FILE:jsref_shell>"
            "-DSCRIPT=${JSREF_DIR}/${script}"
            "-DEXPECTED=${CMAKE_CURRENT_SOURCE_DIR}/expected/${expected}"
            "-DREQUIRED=${_required}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/run_js_test.cmake")
  set_tests_properties(jsref.script.${name} PROPERTIES
    LABELS "jsref"
    TIMEOUT 60
    ENVIRONMENT "${_sanitizer_env}")
endfunction()

jsref_script_test(ycomb ycomb.js ycomb.out
  REQUIRE "5! is 120")
jsref_script_test(perfect perfect.js perfect.out
  REQUIRE "6 = 1 + 2 + 3"
          "28 = 1 + 2 + 4 + 7 + 14"
          "496 = 1 + 2 + 4 + 8 + 16 + 31 + 62 + 124 + 248")

# The ABI gate is built by cmake/components/jsref.cmake as a dependency of
# the engine; its compile-time assertions are the real check.
add_test(NAME jsref.cpucfg.abi COMMAND jsref_cpucfg_check)
set_tests_properties(jsref.cpucfg.abi PROPERTIES
  LABELS "jsref"
  ENVIRONMENT "${_sanitizer_env}")

# New code: embed the engine using only what the jsref target publishes.
# Deliberately no newscape_apply_sanitizers() here: in sanitizer presets this
# links only because jsref passes the sanitizer runtime on to its consumers,
# and the instrumented engine is still checked while it runs.
add_executable(jsref_embed_check embed_check.c)
newscape_new_c_target(jsref_embed_check)
target_link_libraries(jsref_embed_check PRIVATE jsref)
# The program exits 0 only if the script evaluated to 42.
add_test(NAME jsref.embed COMMAND jsref_embed_check)
set_tests_properties(jsref.embed PROPERTIES
  LABELS "jsref"
  ENVIRONMENT "${_sanitizer_env}")

# Header selection, read back from compiler output for every object file:
# the preprocessor's -E -dI view of each real translation unit, and Ninja's
# deps log (the compiler's -MD output). See check_header_selection.py.
# Other generators keep no deps log to inspect.
if(CMAKE_GENERATOR MATCHES "Ninja")
  find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
  add_test(NAME jsref.cpucfg.header_selection
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/check_header_selection.py"
            --ninja "${CMAKE_MAKE_PROGRAM}"
            --build-dir "${PROJECT_BINARY_DIR}"
            --generated "${JSREF_CPUCFG_HEADER}"
            --static "${JSREF_DIR}/prcpucfg.h"
            --site "${JSREF_DIR}/prtypes.h"
            --site "${JSREF_DIR}/prosdep.h"
            --target jsref --target jsref_shell
            --target jsref_cpucfg_check --target jsref_embed_check)
  set_tests_properties(jsref.cpucfg.header_selection PROPERTIES LABELS "jsref")
endif()
