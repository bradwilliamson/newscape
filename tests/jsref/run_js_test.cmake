# Run one script through the js/ref shell and check the whole result.
#
#   cmake -DJS_SHELL=<js> -DSCRIPT=<file.js> -DEXPECTED=<stdout file>
#         [-DREQUIRED=<line>|<line>...] -P run_js_test.cmake
#
# Passes only if the shell exits with status 0, writes nothing to stderr,
# prints exactly the contents of EXPECTED, and prints each REQUIRED line as
# a complete line.
foreach(_var JS_SHELL SCRIPT EXPECTED)
  if(NOT DEFINED ${_var})
    message(FATAL_ERROR "run_js_test.cmake: ${_var} is not set")
  endif()
endforeach()

execute_process(
  COMMAND "${JS_SHELL}" "${SCRIPT}"
  RESULT_VARIABLE _rc
  OUTPUT_VARIABLE _stdout
  ERROR_VARIABLE _stderr
  TIMEOUT 50)

set(_failures "")

if(NOT _rc STREQUAL "0")
  string(APPEND _failures "exit status: ${_rc} (expected 0)\n")
endif()

if(NOT _stderr STREQUAL "")
  string(APPEND _failures "unexpected stderr:\n${_stderr}\n")
endif()

file(READ "${EXPECTED}" _expected)
if(NOT _stdout STREQUAL _expected)
  string(APPEND _failures
    "stdout does not match ${EXPECTED}\n"
    "--- expected ---\n${_expected}"
    "--- actual ---\n${_stdout}"
    "--- end ---\n")
endif()

if(DEFINED REQUIRED AND NOT REQUIRED STREQUAL "")
  string(REPLACE "|" ";" _required "${REQUIRED}")
  foreach(_line IN LISTS _required)
    string(FIND "\n${_stdout}" "\n${_line}\n" _pos)
    if(_pos EQUAL -1)
      string(APPEND _failures "missing required line: ${_line}\n")
    endif()
  endforeach()
endif()

if(NOT _failures STREQUAL "")
  message(FATAL_ERROR "${SCRIPT} failed:\n${_failures}")
endif()
message(STATUS "${SCRIPT}: exit 0, empty stderr, stdout matches")
