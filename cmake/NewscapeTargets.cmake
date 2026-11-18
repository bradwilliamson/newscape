# Per-target build policy. Nothing here is applied globally: historical code
# and code written for newscape get different dialects and warning rules.
include_guard(GLOBAL)

set(NEWSCAPE_SANITIZERS "" CACHE STRING
  "Sanitizers for engine, shell and test targets, e.g. \"address;undefined\"")

# Compatibility flags for 1998 C, so it keeps its original meaning under a
# modern optimizer. Scoped to historical targets only.
set(NEWSCAPE_LEGACY_C_OPTIONS
  # Type punning through pointer casts, e.g. word0()/word1() in js/ref/prdtoa.c.
  -fno-strict-aliasing
  # The code predates compilers that exploit signed-overflow UB.
  -fwrapv
  # Tentative definitions shared across files become one common symbol, as
  # they did by default before GCC 10 and Clang 11. Trade-off: ASan does not
  # add redzones around common symbols.
  -fcommon
)

# Historical code reports warnings but never fails on them. Counts are
# tracked by tools/warning_baseline.py against per-compiler baselines instead.
set(NEWSCAPE_LEGACY_C_WARNINGS -Wall)

# Code written for newscape: warnings are errors.
set(NEWSCAPE_NEW_C_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wstrict-prototypes)

# Compile a target from the historical tree: GNU C89 dialect plus the
# compatibility flags above.
function(newscape_legacy_c_target target)
  set_target_properties(${target} PROPERTIES
    C_STANDARD 90
    C_STANDARD_REQUIRED ON
    C_EXTENSIONS ON
    COMPILE_WARNING_AS_ERROR OFF)
  target_compile_options(${target} PRIVATE
    ${NEWSCAPE_LEGACY_C_OPTIONS} ${NEWSCAPE_LEGACY_C_WARNINGS})
endfunction()

# Compile a target written for newscape: C11, strict warnings, -Werror.
function(newscape_new_c_target target)
  set_target_properties(${target} PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED ON
    C_EXTENSIONS OFF
    COMPILE_WARNING_AS_ERROR ON)
  target_compile_options(${target} PRIVATE ${NEWSCAPE_NEW_C_WARNINGS})
endfunction()

# Instrument a target with NEWSCAPE_SANITIZERS. Build-time host tools are
# deliberately not instrumented. A library's instrumented objects need the
# sanitizer runtimes at final link, so libraries pass the link flag on to
# everything that links them.
function(newscape_apply_sanitizers target)
  if(NOT NEWSCAPE_SANITIZERS)
    return()
  endif()
  list(JOIN NEWSCAPE_SANITIZERS "," _sanitizers)
  target_compile_options(${target} PRIVATE
    -fsanitize=${_sanitizers} -fno-sanitize-recover=all -fno-omit-frame-pointer)
  get_target_property(_type ${target} TYPE)
  if(_type MATCHES "LIBRARY$")
    target_link_options(${target} INTERFACE -fsanitize=${_sanitizers})
  else()
    target_link_options(${target} PRIVATE -fsanitize=${_sanitizers})
  endif()
endfunction()
