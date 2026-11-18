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

The targets must be up to date (`ninja -n` has no work), so both views
describe the sources as they are now. Objects that include no CPU
configuration at all (e.g. jslock.c, empty unless JS_THREADSAFE is defined)
are listed as exempt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

LINEMARKER = re.compile(r'^# \d+ "((?:[^"\\]|\\.)*)"((?: \d+)*)\s*$')
DIRECTIVE = re.compile(r'^#\s*include\s*(["<])([^">]*)[">]')
DEPS_HEADER = re.compile(r"^(\S.*): #deps \d+, deps mtime \d+ \((\w+)\)$")


def norm(path: str, base: str) -> str:
    return os.path.normpath(os.path.join(base, path))


def owner(output: str, targets: list[str]) -> str | None:
    for target in targets:
        if f"CMakeFiles/{target}.dir/" in output:
            return target
    return None


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


def check_translation_unit(entry: dict, generated: str, sites: set[str],
                           failures: list[str]) -> tuple[set[str], set[str]]:
    """Return (sites with an active prcpucfg directive, prcpucfg files opened)."""
    obj = entry["output"]
    result = subprocess.run(preprocess_command(entry["command"], entry["file"]),
                            cwd=entry["directory"], capture_output=True, text=True)
    if result.returncode != 0:
        failures.append(f"{obj}: preprocessing failed:\n{result.stderr}")
        return set(), set()

    current = None
    entered_sites: set[str] = set()
    sites_with_directive: set[str] = set()
    opened: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("#"):
            continue
        m = LINEMARKER.match(line)
        if m:
            # Line markers escape '"' and '\' with a backslash; flag 1 means
            # the preprocessor is entering a newly opened file.
            path = norm(re.sub(r"\\(.)", r"\1", m[1]), entry["directory"])
            if "1" in m[2].split():
                if path in sites:
                    entered_sites.add(path)
                if os.path.basename(path) == "prcpucfg.h":
                    opened.add(path)
                    if path != generated:
                        failures.append(f"{obj}: opened {path} (included from {current})")
            current = path
            continue
        d = DIRECTIVE.match(line)
        if d and os.path.basename(d[2]) == "prcpucfg.h":
            spelled = d[2]
            if not (os.path.isabs(spelled) and os.path.normpath(spelled) == generated):
                failures.append(f"{obj}: directive in {current} spells "
                                f"{d[1]}{spelled}, not the generated header")
            if current in sites:
                sites_with_directive.add(current)

    for site in sorted(entered_sites - sites_with_directive):
        failures.append(f"{obj}: enters {site} but no prcpucfg.h directive "
                        "is active in it")
    return sites_with_directive, opened


def read_deps_log(ninja: str, build_dir: str) -> dict[str, tuple[str, set[str]]]:
    out = subprocess.run([ninja, "-C", build_dir, "-t", "deps"], check=True,
                         capture_output=True, text=True).stdout
    records: dict[str, tuple[str, set[str]]] = {}
    current = None
    for line in out.splitlines():
        m = DEPS_HEADER.match(line)
        if m:
            current = m[1]
            records[current] = (m[2], set())
        elif current and line.startswith("    "):
            records[current][1].add(norm(line.strip(), build_dir))
    return records


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ninja", required=True)
    p.add_argument("--build-dir", required=True)
    p.add_argument("--generated", required=True)
    p.add_argument("--static", required=True)
    p.add_argument("--site", action="append", required=True)
    p.add_argument("--target", action="append", required=True)
    a = p.parse_args()

    build_dir = os.path.normpath(a.build_dir)
    generated = os.path.normpath(a.generated)
    static = os.path.normpath(a.static)
    sites = {os.path.normpath(s) for s in a.site}
    failures: list[str] = []

    dry = subprocess.run([a.ninja, "-C", build_dir, "-n", *a.target],
                         capture_output=True, text=True)
    if dry.returncode != 0 or "ninja: no work to do" not in dry.stdout:
        sys.exit("build is not up to date; rebuild before checking:\n"
                 + dry.stdout + dry.stderr)

    entries = json.loads(Path(build_dir, "compile_commands.json").read_text())
    expected = [e for e in entries if owner(e["output"], a.target)]
    if not expected:
        sys.exit(f"no objects for {a.target} in compile_commands.json")

    # 1. Preprocessor view of every real translation unit.
    sites_seen: set[str] = set()
    for entry in expected:
        with_directive, _ = check_translation_unit(entry, generated, sites, failures)
        sites_seen |= with_directive
    for site in sorted(sites - sites_seen):
        failures.append(f"{site}: no translation unit has an active prcpucfg.h "
                        "directive in it")

    # 2. The compiler's -MD output, as recorded by Ninja.
    records = read_deps_log(a.ninja, build_dir)
    generated_by_target = {t: 0 for t in a.target}
    exempt = []
    for entry in expected:
        obj = entry["output"]
        if obj not in records:
            failures.append(f"{obj}: no record in the deps log")
            continue
        state, deps = records[obj]
        if state != "VALID":
            failures.append(f"{obj}: deps record is {state}")
        cpucfg = {d for d in deps if os.path.basename(d) == "prcpucfg.h"}
        for d in sorted(cpucfg - {generated}):
            kind = "the static" if d == static else "an unexpected"
            failures.append(f"{obj}: depends on {kind} {d}")
        if generated in cpucfg:
            generated_by_target[owner(obj, a.target)] += 1
        elif deps & sites:
            failures.append(f"{obj}: depends on an include site but not {generated}")
        else:
            exempt.append(obj)
    for target, n in generated_by_target.items():
        if n == 0:
            failures.append(f"{target}: no object depends on {generated}")

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
        print(f"exempt (includes no CPU configuration): {obj}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
