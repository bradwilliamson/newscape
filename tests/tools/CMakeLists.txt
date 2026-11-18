# Regression checks for the build verification scripts themselves.
#
# With Ninja (every preset) the verification scripts need Python anyway, so
# it is required. Other generators do not use the scripts: there the check
# runs if Python is available and is skipped, visibly, if not.
if(CMAKE_GENERATOR MATCHES "Ninja")
  find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
else()
  find_package(Python3 3.8 COMPONENTS Interpreter)
endif()

if(Python3_Interpreter_FOUND)
  # -B: write no bytecode caches into the source tree.
  add_test(NAME tools.object_paths
    COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_CURRENT_SOURCE_DIR}/test_object_paths.py")
  set_tests_properties(tools.object_paths PROPERTIES LABELS "tools")
else()
  message(STATUS "Python 3.8+ not found: skipping the tools.object_paths test")
endif()
