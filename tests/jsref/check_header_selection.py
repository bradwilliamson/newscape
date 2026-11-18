#!/usr/bin/env python3
"""Verify which prcpucfg.h the js/ref build selected, from compiler output.

For every object file the build produces for the given targets (taken from
compile_commands.json), this checks two kinds of compiler output:

1. The preprocessor's view of the real translation unit, run with the exact
   compile flags plus -E -dI. -dI echoes each active #include directive, as
   spelled after macro expansion, inside the file that contains it, and line
   markers show which file each header was opened from. Requirements:
     - every active directive naming prcpucfg.h spells the generated header;
     - every include site the unit enters has such a directive active in it,
       so a site cannot be silently disabled (e.g. by #if around it);
     - every prcpucfg.h actually opened is the generated header.
2. Ninja's deps log, which records the compiler's -MD dependency output.
   Every object must have an up-to-date record, no object may depend on the
   static js/ref/prcpucfg.h or any other copy, and every object that depends
   on an include site must depend on the generated header.

Object paths are compared in canonical form (tools/buildpaths.py), because
compile_commands.json spells them relative (CMake 3.x) or absolute (CMake
4.x) while Ninja spells them relative to the build directory.

The targets must be up to date (`ninja -n` has no work), so both views
describe the sources as they are now. Objects that include no CPU
configuration at all (e.g. jslock.c, empty unless JS_THREADSAFE is defined)
are listed as exempt.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep generated files out of the source tree


def _load_buildpaths():
    """Load tools/buildpaths.py by path, without changing sys.path."""
    path = Path(__file__).resolve().parents[2] / "tools" / "buildpaths.py"
    spec = importlib.util.spec_from_file_location("newscape_buildpaths", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


buildpaths = _load_buildpaths()
canonical = buildpaths.canonical
entry_object = buildpaths.entry_object
is_same_file = buildpaths.is_same_file
names_file = buildpaths.names_file
resolve_object = buildpaths.resolve_object
same_inode = buildpaths.same_inode
ninja_path = buildpaths.ninja_path
target_of = buildpaths.target_of

CPUCFG = "prcpucfg.h"


def is_cpucfg(path: str, generated: str, static: str) -> bool:
    """`path` is a CPU configuration header: named prcpucfg.h, resolving to a
    file of that name, or the same file on disk as the generated or static
    header (a hard link under another name)."""
    return (names_file(path, CPUCFG) or same_inode(path, generated)
            or same_inode(path, static))


def is_static_header(path: str, static: str) -> bool:
    return (path == static or os.path.realpath(path) == os.path.realpath(static)
            or same_inode(path, static))

LINEMARKER = re.compile(r'^# \d+ "((?:[^"\\]|\\.)*)"((?: \d+)*)\s*$')
DIRECTIVE = re.compile(r'^#\s*include\s*(["<])([^">]*)[">]')
DEPS_HEADER = re.compile(r"^(\S.*): #deps \d+, deps mtime \d+ \((\w+)\)$")


def select_expected(entries: list[dict], targets: list[str], build_dir: str
                    ) -> tuple[dict[str, dict], list[str]]:
    """Canonical object path -> compile_commands.json entry, for the targets.

    The target is read from the object path as spelled below the build
    directory, before any symlink is resolved. Also returns failures for
    object paths that go through a symlink, and for two entries that name
    the same object.
    """
    expected: dict[str, dict] = {}
    failures: list[str] = []
    for entry in entries:
        obj = entry_object(entry, build_dir)
        if not target_of(obj.rel, targets):
            continue
        if obj.problem:
            failures.append(f"{obj.spelled}: object path {obj.problem}")
        if obj.path in expected:
            failures.append(f"{obj.spelled}: names the same object as another "
                            "compile command")
        expected[obj.path] = entry
    return expected, failures


def parse_deps_log(text: str, build_dir: str) -> dict[str, tuple[str, set[str]]]:
    """Parse `ninja -t deps` output into canonical object -> (state, deps).

    Two records that resolve to the same object are marked AMBIGUOUS, which
    check_deps() reports as a failure.
    """
    records: dict[str, tuple[str, set[str]]] = {}
    current = None
    for line in text.splitlines():
        m = DEPS_HEADER.match(line)
        if m:
            current = ninja_path(m[1], build_dir)
            state = "AMBIGUOUS" if current in records else m[2]
            records[current] = (state, set())
        elif current and line.startswith("    "):
            records[current][1].add(ninja_path(line.strip(), build_dir))
    return records


def check_deps(expected: dict[str, dict], records: dict[str, tuple[str, set[str]]],
               generated: str, static: str, sites: set[str], targets: list[str],
               build_dir: str) -> tuple[list[str], dict[str, int], list[str]]:
    """Check every expected object against the deps log.

    Returns (failures, objects depending on the generated header per target,
    exempt objects).
    """
    failures: list[str] = []
    generated_by_target = {t: 0 for t in targets}
    exempt: list[str] = []
    for obj, entry in expected.items():
        if obj not in records:
            failures.append(f"{obj}: no record in the deps log")
            continue
        state, deps = records[obj]
        if state != "VALID":
            failures.append(f"{obj}: deps record is {state}")
        # A CPU configuration header is anything named prcpucfg.h or resolving
        # to a file of that name; only the real generated file is acceptable.
        cpucfg = {d for d in deps if is_cpucfg(d, generated, static)}
        good = {d for d in cpucfg if is_same_file(d, generated)}
        for d in sorted(cpucfg - good):
            kind = "the static" if is_static_header(d, static) else "an unexpected"
            failures.append(f"{obj}: depends on {kind} {d}")
        if good:
            rel = entry_object(entry, build_dir).rel
            generated_by_target[target_of(rel, targets)] += 1
        elif deps & sites:
            failures.append(f"{obj}: depends on an include site but not {generated}")
        else:
            exempt.append(obj)
    for target, n in generated_by_target.items():
        if n == 0:
            failures.append(f"{target}: no object depends on {generated}")
    return failures, generated_by_target, exempt


def preprocess_command(command: str, source: str) -> list[str]:
    """The compile command with output and dependency-file options dropped."""
    args, skip = [], False
    for tok in shlex.split(command):
        if skip:
            skip = False
        elif tok in ("-o", "-c", "-MT", "-MF", "-MQ"):
            skip = True
        elif tok not in ("-MD", "-MMD"):
            args.append(tok)
    return args + ["-E", "-dI", source]


def check_translation_unit(obj: str, entry: dict, generated: str, static: str,
                           sites: set[str], failures: list[str]) -> set[str]:
    """Check one unit's -E -dI output; return the sites with an active directive."""
    directory = entry["directory"]
    result = subprocess.run(preprocess_command(entry["command"], entry["file"]),
                            cwd=directory, capture_output=True, text=True)
    if result.returncode != 0:
        failures.append(f"{obj}: preprocessing failed:\n{result.stderr}")
        return set()

    current = None
    entered_sites: set[str] = set()
    sites_with_directive: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("#"):
            continue
        m = LINEMARKER.match(line)
        if m:
            # Line markers escape '"' and '\' with a backslash; flag 1 means
            # the preprocessor is entering a newly opened file.
            path = canonical(re.sub(r"\\(.)", r"\1", m[1]), directory)
            if "1" in m[2].split():
                if path in sites:
                    entered_sites.add(path)
                if is_cpucfg(path, generated, static) and not is_same_file(path, generated):
                    failures.append(f"{obj}: opened {path} (included from {current})")
            current = path
            continue
        d = DIRECTIVE.match(line)
        if d and os.path.basename(d[2]) == CPUCFG:
            spelled = d[2]
            if not (os.path.isabs(spelled) and is_same_file(spelled, generated)):
                failures.append(f"{obj}: directive in {current} spells "
                                f"{d[1]}{spelled}, not the generated header")
            if current in sites:
                sites_with_directive.add(current)

    for site in sorted(entered_sites - sites_with_directive):
        failures.append(f"{obj}: enters {site} but no prcpucfg.h directive "
                        "is active in it")
    return sites_with_directive


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ninja", required=True)
    p.add_argument("--build-dir", required=True)
    p.add_argument("--generated", required=True)
    p.add_argument("--static", required=True)
    p.add_argument("--site", action="append", required=True)
    p.add_argument("--target", action="append", required=True)
    a = p.parse_args()

    build_dir = os.path.realpath(a.build_dir)
    cwd = os.getcwd()
    generated = canonical(a.generated, cwd)
    static = canonical(a.static, cwd)
    sites = {canonical(s, cwd) for s in a.site}
    failures: list[str] = []
    # The generated header must be a real file in the build directory, reached
    # without symlinks (so it cannot be redirected outside out/<preset>).
    generated_problem = resolve_object(a.generated, cwd, build_dir).problem
    if generated_problem or os.path.realpath(generated) != generated:
        failures.append(f"{a.generated}: generated header path "
                        f"{generated_problem or 'is a symlink'}")

    dry = subprocess.run([a.ninja, "-C", build_dir, "-n", *a.target],
                         capture_output=True, text=True)
    if dry.returncode != 0 or "ninja: no work to do" not in dry.stdout:
        sys.exit("build is not up to date; rebuild before checking:\n"
                 + dry.stdout + dry.stderr)

    entries = json.loads(Path(build_dir, "compile_commands.json").read_text())
    expected, select_failures = select_expected(entries, a.target, build_dir)
    failures += select_failures
    if not expected:
        sys.exit(f"no objects for {a.target} in compile_commands.json")

    # 1. Preprocessor view of every real translation unit.
    sites_seen: set[str] = set()
    for obj, entry in expected.items():
        sites_seen |= check_translation_unit(obj, entry, generated, static, sites, failures)
    for site in sorted(sites - sites_seen):
        failures.append(f"{site}: no translation unit has an active prcpucfg.h "
                        "directive in it")

    # 2. The compiler's -MD output, as recorded by Ninja.
    deps_text = subprocess.run([a.ninja, "-C", build_dir, "-t", "deps"], check=True,
                               capture_output=True, text=True).stdout
    records = parse_deps_log(deps_text, build_dir)
    deps_failures, generated_by_target, exempt = check_deps(
        expected, records, generated, static, sites, a.target, build_dir)
    failures += deps_failures

    if failures:
        print("prcpucfg.h selection check failed:")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"{len(expected)} translation units in {a.target}: every active "
          f"prcpucfg.h directive spells {generated}, and every opened copy is it")
    for site in sorted(sites):
        print(f"include site {site}: directive active and generated")
    print(f"deps log: {sum(generated_by_target.values())} objects depend on the "
          f"generated header, none on {static}")
    for obj in exempt:
        print(f"exempt (includes no CPU configuration): {os.path.relpath(obj, build_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
