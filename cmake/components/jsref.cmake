# js/ref: the standalone JavaScript 1.3 reference engine and its shell.
# Source lists mirror LIB_CFILES and PROG_CFILES in js/ref/Makefile.

set(JSREF_DIR "${PROJECT_SOURCE_DIR}/js/ref")
set(JSREF_GENERATED_DIR "${PROJECT_BINARY_DIR}/generated/jsref")
set(JSREF_CPUCFG_HEADER "${JSREF_GENERATED_DIR}/prcpucfg.h")

# Defines from js/ref/config/Linux_All.mk and the Makefile's CFLAGS, with
# _BSD_SOURCE replaced by its glibc successor _DEFAULT_SOURCE.
# NEWSCAPE_CMAKE_BUILD selects the modern-toolchain path in os/linux.h;
# historical builds never define it.
set(JSREF_DEFINES
  XP_UNIX SVR4 SYSV _DEFAULT_SOURCE POSIX_SOURCE LINUX JSFILE
  NEWSCAPE_CMAKE_BUILD
  $<$<CONFIG:Debug>:DEBUG>)

# --- CPU configuration ------------------------------------------------------
# prcpucfg.c probes the host's type sizes, alignments and byte order and
# prints prcpucfg.h. The static js/ref/prcpucfg.h only covers 1998 targets
# (no x86-64). prtypes.h and prosdep.h include the file named by
# NEWSCAPE_PRCPUCFG_H when it is defined, so the generated header is selected
# by its exact path, independent of include-path order. Historical builds
# leave it undefined and keep their original "prcpucfg.h" lookup.
add_executable(jsref_cpucfg_gen "${JSREF_DIR}/prcpucfg.c")
newscape_legacy_c_target(jsref_cpucfg_gen)
target_compile_definitions(jsref_cpucfg_gen PRIVATE ${JSREF_DEFINES})

add_custom_command(
  OUTPUT "${JSREF_CPUCFG_HEADER}"
  COMMAND "${CMAKE_COMMAND}"
          "-DPROGRAM=$<TARGET_FILE:jsref_cpucfg_gen>"
          "-DOUTPUT=${JSREF_CPUCFG_HEADER}"
          -P "${PROJECT_SOURCE_DIR}/cmake/RunToFile.cmake"
  DEPENDS jsref_cpucfg_gen "${PROJECT_SOURCE_DIR}/cmake/RunToFile.cmake"
  COMMENT "Generating js/ref CPU configuration (prcpucfg.h)"
  VERBATIM)
add_custom_target(jsref_cpucfg DEPENDS "${JSREF_CPUCFG_HEADER}")

# ABI gate (new code): compile-time assertions that the generated header
# matches the compiler's type sizes, alignments and byte order. The engine
# and shell depend on it, so a wrong header stops any build of them, not
# just a full build. tests/jsref also runs it as a CTest.
add_executable(jsref_cpucfg_check "${PROJECT_SOURCE_DIR}/tests/jsref/cpucfg_check.c")
add_dependencies(jsref_cpucfg_check jsref_cpucfg)
newscape_new_c_target(jsref_cpucfg_check)
newscape_apply_sanitizers(jsref_cpucfg_check)
target_compile_definitions(jsref_cpucfg_check PRIVATE
  "NEWSCAPE_PRCPUCFG_H=\"${JSREF_CPUCFG_HEADER}\"")

# --- Engine library ---------------------------------------------------------
set(JSREF_LIB_SOURCES
  prarena.c prassert.c prdtoa.c prhash.c prlog2.c prlong.c prprintf.c prtime.c
  jsapi.c jsarray.c jsatom.c jsbool.c jscntxt.c jsdate.c jsdbgapi.c jsemit.c
  jsfun.c jsgc.c jsinterp.c jslock.c jsmath.c jsnum.c jsobj.c jsopcode.c
  jsparse.c jsregexp.c jsscan.c jsscope.c jsscript.c jsstr.c jsxdrapi.c)
list(TRANSFORM JSREF_LIB_SOURCES PREPEND "${JSREF_DIR}/")

add_library(jsref STATIC ${JSREF_LIB_SOURCES})
add_dependencies(jsref jsref_cpucfg jsref_cpucfg_check)
newscape_legacy_c_target(jsref)
newscape_apply_sanitizers(jsref)
target_compile_definitions(jsref PUBLIC
  ${JSREF_DEFINES}
  "NEWSCAPE_PRCPUCFG_H=\"${JSREF_CPUCFG_HEADER}\"")
# js/ref sources find each other through quoted includes relative to their
# own directory, so the library itself needs no include path. Programs that
# link jsref get js/ref for jsapi.h, as a system directory so the 1998
# headers do not trip their warnings.
target_include_directories(jsref SYSTEM INTERFACE "${JSREF_DIR}")
target_link_libraries(jsref PUBLIC m)

# --- Shell ------------------------------------------------------------------
add_executable(jsref_shell "${JSREF_DIR}/js.c")
set_target_properties(jsref_shell PROPERTIES OUTPUT_NAME js)
add_dependencies(jsref_shell jsref_cpucfg jsref_cpucfg_check)
newscape_legacy_c_target(jsref_shell)
newscape_apply_sanitizers(jsref_shell)
target_link_libraries(jsref_shell PRIVATE jsref)
