# Run PROGRAM and write its standard output to OUTPUT.
#
#   cmake -DPROGRAM=<executable> -DOUTPUT=<file> -P RunToFile.cmake
#
# The file is replaced only after the program succeeds, so a failed run
# never leaves a truncated header behind.
foreach(_var PROGRAM OUTPUT)
  if(NOT DEFINED ${_var})
    message(FATAL_ERROR "RunToFile.cmake: ${_var} is not set")
  endif()
endforeach()

get_filename_component(_dir "${OUTPUT}" DIRECTORY)
file(MAKE_DIRECTORY "${_dir}")

execute_process(
  COMMAND "${PROGRAM}"
  OUTPUT_FILE "${OUTPUT}.tmp"
  RESULT_VARIABLE _rc)
if(NOT _rc STREQUAL "0")
  file(REMOVE "${OUTPUT}.tmp")
  message(FATAL_ERROR "${PROGRAM} failed: ${_rc}")
endif()
file(RENAME "${OUTPUT}.tmp" "${OUTPUT}")
