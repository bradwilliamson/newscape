#!/usr/bin/env python3
"""Per-compiler warning baselines for historical code.

Historical targets build with warnings on but never with -Werror. This tool
keeps their warning counts from growing: it clean-rebuilds a preset, counts
unique warnings per (file, warning flag), and compares against the committed
baseline for that compiler.

    tools/warnings.py record gcc     # rebuild gcc-debug, rewrite tools/warnings/gcc.tsv
    tools/warnings.py check clang    # rebuild clang-debug, fail if any count grew

A warning is unique by file, line, column, flag and message, so a warning in a
header counts once no matter how many translation units include it. The tool
refuses to trust a build log unless it shows every compile command in
compile_commands.json running, and it fails on any warning line it cannot
parse rather than skipping it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT / "tools" / "warnings"
PRESETS = {"gcc": "gcc-debug", "clang": "clang-debug"}

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# file:line:col: warning: ..., with line and column each optional (e.g.
# -fno-show-column, or driver/linker warnings that name only a file).
WARNING = re.compile(
    r"^(?P<file>[^\s:][^:]*?)(?::(?P<line>\d+))?(?::(?P<col>\d+))?: warning: "
    r"(?P<msg>.*?)(?: \[(?P<flag>-W[^\]]+)\])?$"
)
NINJA_COMPILE = re.compile(r"^\[\d+/\d+\] Building C object (?P<output>\S+)$")

Key = tuple[str, str]  # (file relative to the repo, warning flag)


def relative(path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return p.as_posix()
    return p.as_posix()


def count_warnings(log: str) -> Counter[Key]:
    unique: set[tuple[str, str, str, str, str]] = set()
    unparsed = []
    for raw in log.splitlines():
        line = ANSI.sub("", raw).rstrip()
        m = WARNING.match(line)
        if m:
            unique.add((relative(m["file"]), m["line"] or "", m["col"] or "",
                        m["flag"] or "(no flag)", m["msg"]))
        elif "warning:" in line:
            unparsed.append(line)
    if unparsed:
        sys.exit("unrecognized warning format; refusing to undercount:\n  "
                 + "\n  ".join(unparsed))
    return Counter((f, flag) for f, _, _, flag, _ in unique)


def require_full_build(log: str, build_dir: Path) -> None:
    entries = json.loads((build_dir / "compile_commands.json").read_text())
    expected = {e["output"] for e in entries}
    compiled = {m["output"] for m in map(NINJA_COMPILE.match, log.splitlines()) if m}
    missing = sorted(expected - compiled)
    if missing:
        sys.exit("build log does not show these objects compiling, so their "
                 "warnings would be missed:\n  " + "\n  ".join(missing))


# Compiler options that would hide warnings or change their format.
HIDING_OPTIONS = re.compile(r"(?:^|\s)(-w|-fdiagnostics-format=\S+|"
                            r"-fno-diagnostics-show-option)(?=\s|$)")


def controlled_env() -> dict[str, str]:
    """Environment for a baseline build: the preset's flags only, C locale."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CFLAGS", "CPPFLAGS", "LDFLAGS", "LANGUAGE")}
    env["LC_ALL"] = env["LANG"] = "C"
    return env


def require_preset_flags(build_dir: Path) -> None:
    entries = json.loads((build_dir / "compile_commands.json").read_text())
    for e in entries:
        m = HIDING_OPTIONS.search(e["command"])
        if m:
            sys.exit(f"{e['output']} compiles with {m[1]}, which would hide or "
                     "reformat warnings; baselines need the preset's own flags")


def full_build_log(preset: str) -> str:
    env = controlled_env()
    # --fresh drops any cached CMAKE_C_FLAGS etc., so the build uses exactly
    # the preset's configuration.
    subprocess.run(["cmake", "--preset", preset, "--fresh"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL, env=env)
    build_dir = ROOT / "out" / preset
    require_preset_flags(build_dir)
    result = subprocess.run(
        ["cmake", "--build", "--preset", preset, "--clean-first"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=env)
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.exit(f"build of preset {preset} failed")
    require_full_build(result.stdout, build_dir)
    return result.stdout


def baseline_path(compiler: str) -> Path:
    return BASELINE_DIR / f"{compiler}.tsv"


def read_baseline(compiler: str) -> Counter[Key]:
    counts: Counter[Key] = Counter()
    path = baseline_path(compiler)
    if not path.exists():
        sys.exit(f"no baseline at {path.relative_to(ROOT)}; run `record {compiler}` first")
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        count, flag, file = line.split("\t")
        counts[(file, flag)] = int(count)
    return counts


def write_baseline(compiler: str, counts: Counter[Key]) -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Warning baseline for {compiler} (preset {PRESETS[compiler]}).",
        "# Unique warnings per file and flag. Regenerate with:",
        f"#   tools/warnings.py record {compiler}",
        f"# total\t{sum(counts.values())}",
        "# count\tflag\tfile",
    ]
    for (file, flag), n in sorted(counts.items()):
        lines.append(f"{n}\t{flag}\t{file}")
    baseline_path(compiler).write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["record", "check"])
    parser.add_argument("compiler", choices=sorted(PRESETS))
    args = parser.parse_args()

    current = count_warnings(full_build_log(PRESETS[args.compiler]))

    if args.mode == "record":
        write_baseline(args.compiler, current)
        print(f"recorded {sum(current.values())} warnings in "
              f"{len(current)} (file, flag) groups to "
              f"{baseline_path(args.compiler).relative_to(ROOT)}")
        return 0

    baseline = read_baseline(args.compiler)
    regressions = []
    improvements = []
    for key in sorted(set(current) | set(baseline)):
        now, before = current.get(key, 0), baseline.get(key, 0)
        if now > before:
            regressions.append((key, before, now))
        elif now < before:
            improvements.append((key, before, now))

    for (file, flag), before, now in regressions:
        print(f"MORE  {file} {flag}: {before} -> {now}")
    for (file, flag), before, now in improvements:
        print(f"FEWER {file} {flag}: {before} -> {now}")
    print(f"{args.compiler}: {sum(current.values())} warnings "
          f"(baseline {sum(baseline.values())})")
    if regressions:
        print("warning count grew; fix the new warnings")
        return 1
    if improvements:
        print(f"fewer warnings than the baseline; lock it in with "
              f"`tools/warnings.py record {args.compiler}`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
