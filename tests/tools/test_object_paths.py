#!/usr/bin/env python3
"""Regression check: object identity in the build verification scripts.

tests/jsref/check_header_selection.py and tools/warning_baseline.py both
compare object paths from compile_commands.json with paths Ninja reports.
CMake 3.x writes "output" relative to the entry's "directory", CMake 4.x
writes it absolute, and Ninja is relative to the build directory. These cases
feed both scripts mixed spellings (relative, absolute, "..", a symlinked
build directory, and an entry whose directory is a subdirectory of the
build), plus one genuinely missing object, which both must still report.

They also cover what normalization must not allow:
- a decoy with the missing object's file name satisfying it;
- a symlinked object file or object directory (including one linked to the
  build root itself) standing in for another object, or hiding one;
- a symlink or hard link to the static prcpucfg.h, under any name, passing
  as the generated header, or a generated header reached through a symlink;
- the build directory's own location deciding which target owns an object;
- a "warnings" module in tools/ shadowing the standard library.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # keep generated files out of the source tree
ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


header_check = load("newscape_check_header_selection",
                    ROOT / "tests" / "jsref" / "check_header_selection.py")
baseline_tool = load("newscape_warning_baseline", ROOT / "tools" / "warning_baseline.py")
buildpaths = load("newscape_buildpaths_under_test", ROOT / "tools" / "buildpaths.py")

OBJ_DIR = "CMakeFiles/jsref.dir/js/ref"
SUB_OBJ = "tests/jsref/CMakeFiles/jsref.dir/sub.c.o"     # under a subdirectory


class Scenario:
    """A build directory with compile_commands.json entries and Ninja names."""

    def __init__(self, top: Path) -> None:
        self.top = top
        self.build = top / "real build"          # a space, as in Codex's run
        (self.build / "tests" / "jsref").mkdir(parents=True)
        self.linked = top / "linked-build"       # symlink to the same build dir
        self.linked.symlink_to(self.build)
        b, l = str(self.build), str(self.linked)
        self.generated = str(self.build / "generated" / "jsref" / "prcpucfg.h")
        self.static = str(top / "src" / "js" / "ref" / "prcpucfg.h")

        self.entries = [
            {"directory": b, "output": f"{OBJ_DIR}/rel.c.o"},              # CMake 3.x
            {"directory": b, "output": f"{b}/{OBJ_DIR}/abs.c.o"},          # CMake 4.x
            {"directory": l, "output": f"{OBJ_DIR}/via_link.c.o"},
            {"directory": b, "output": f"{l}/{OBJ_DIR}/abs_via_link.c.o"},
            {"directory": b, "output": f"tests/../{OBJ_DIR}/dotdot.c.o"},
            # Relative to its own directory, not the build directory: a script
            # that used the wrong base would look for CMakeFiles/jsref.dir/sub.c.o.
            {"directory": f"{b}/tests/jsref", "output": "CMakeFiles/jsref.dir/sub.c.o"},
            {"directory": b, "output": f"{OBJ_DIR}/missing.c.o"},          # never built
            {"directory": b, "output": "CMakeFiles/other.dir/unrelated.c.o"},
        ]
        self.missing = os.path.join(b, OBJ_DIR, "missing.c.o")

        # Ninja's names cross the spellings above; the last is a decoy with
        # the missing object's file name under another target.
        self.ninja_names = [
            f"{b}/{OBJ_DIR}/rel.c.o",
            f"{OBJ_DIR}/abs.c.o",
            f"{l}/{OBJ_DIR}/via_link.c.o",
            f"{OBJ_DIR}/abs_via_link.c.o",
            f"{OBJ_DIR}/../ref/dotdot.c.o",
            SUB_OBJ,
            "CMakeFiles/other.dir/js/ref/missing.c.o",
        ]

    def write_headers(self) -> None:
        Path(self.generated).parent.mkdir(parents=True, exist_ok=True)
        Path(self.generated).write_text("/* generated */\n")
        Path(self.static).parent.mkdir(parents=True, exist_ok=True)
        Path(self.static).write_text("/* static */\n")

    @staticmethod
    def deps_log(names: list[str], deps: tuple = ("generated/jsref/prcpucfg.h",)) -> str:
        out = []
        for name in names:
            out += [f"{name}: #deps {len(deps)}, deps mtime 1 (VALID)"]
            out += [f"    {d}" for d in deps] + [""]
        return "\n".join(out)

    @staticmethod
    def compile_log(names: list[str]) -> str:
        return "\n".join(f"[{i}/{len(names)}] Building C object {n}"
                         for i, n in enumerate(names, 1))

    def header_failures(self, entries: list[dict], base: str, log: str = "") -> list[str]:
        expected, failures = header_check.select_expected(entries, ["jsref"], base)
        records = header_check.parse_deps_log(log or self.deps_log(self.ninja_names), base)
        deps_failures, _, _ = header_check.check_deps(
            expected, records, self.generated, self.static, set(), ["jsref"], base)
        return failures + deps_failures


class ObjectPaths(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.top = Path(os.path.realpath(self._tmp.name))
        self.s = Scenario(self.top)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def b(self) -> str:
        return str(self.s.build)

    # --- spellings and the missing object ---------------------------------

    def test_header_check_selects_only_listed_targets(self) -> None:
        expected, failures = header_check.select_expected(
            self.s.entries, ["jsref"], self.b())
        self.assertEqual(failures, [])
        self.assertEqual(len(expected), 7)
        self.assertIn(self.s.missing, expected)
        self.assertIn(str(self.s.build / SUB_OBJ), expected)
        self.assertFalse(any("unrelated" in obj for obj in expected))

    def test_header_check_matches_every_spelling_and_fails_the_missing_one(self) -> None:
        for base in (self.b(), str(self.s.linked)):
            with self.subTest(ninja_base=base):
                self.assertEqual(self.s.header_failures(self.s.entries, base),
                                 [f"{self.s.missing}: no record in the deps log"])

    def test_header_check_passes_when_nothing_is_missing(self) -> None:
        present = [e for e in self.s.entries if not e["output"].endswith("missing.c.o")]
        self.assertEqual(self.s.header_failures(present, self.b()), [])

    def test_baseline_tool_matches_every_spelling_and_fails_the_missing_one(self) -> None:
        names = self.s.ninja_names + ["CMakeFiles/other.dir/unrelated.c.o"]
        for base in (self.b(), str(self.s.linked)):
            with self.subTest(ninja_base=base):
                missing = baseline_tool.missing_compiles(
                    self.s.entries, self.s.compile_log(names), base)
                self.assertEqual(missing, [self.s.missing])

    def test_baseline_tool_passes_when_nothing_is_missing(self) -> None:
        names = self.s.ninja_names + [f"{OBJ_DIR}/missing.c.o",
                                      "CMakeFiles/other.dir/unrelated.c.o"]
        self.assertEqual(baseline_tool.missing_compiles(
            self.s.entries, self.s.compile_log(names), self.b()), [])

    def test_baseline_tool_full_build_gate_exits_on_the_missing_object(self) -> None:
        (self.s.build / "compile_commands.json").write_text(json.dumps(self.s.entries))
        names = self.s.ninja_names + ["CMakeFiles/other.dir/unrelated.c.o"]
        with self.assertRaises(SystemExit) as raised:
            baseline_tool.require_full_build(self.s.compile_log(names), self.s.linked)
        self.assertIn(self.s.missing, str(raised.exception))

    # --- symlinks inside the build directory -------------------------------

    def symlinked_object_file(self) -> list[dict]:
        objdir = self.s.build / OBJ_DIR
        objdir.mkdir(parents=True)
        (objdir / "real.c.o").write_bytes(b"real")
        (objdir / "alias.c.o").symlink_to(objdir / "real.c.o")
        return [{"directory": self.b(), "output": f"{OBJ_DIR}/real.c.o"},
                {"directory": self.b(), "output": f"{OBJ_DIR}/alias.c.o"}]

    def symlinked_object_dir(self) -> list[dict]:
        """CMakeFiles/jsref.dir/sub moved out of the build and linked back."""
        outside = self.top / "elsewhere" / "sub"
        outside.mkdir(parents=True)
        (outside / "bad.c.o").write_bytes(b"bad")
        (self.s.build / "CMakeFiles" / "jsref.dir").mkdir(parents=True)
        (self.s.build / "CMakeFiles" / "jsref.dir" / "sub").symlink_to(outside)
        return [{"directory": self.b(), "output": "CMakeFiles/jsref.dir/sub/bad.c.o"}]

    def symlinked_target_dir(self) -> list[dict]:
        """CMakeFiles/excluded.dir linked to CMakeFiles/active.dir."""
        active = self.s.build / "CMakeFiles" / "active.dir"
        active.mkdir(parents=True)
        (active / "test.c.o").write_bytes(b"x")
        (self.s.build / "CMakeFiles" / "excluded.dir").symlink_to(active)
        return [{"directory": self.b(), "output": "CMakeFiles/active.dir/test.c.o"},
                {"directory": self.b(), "output": "CMakeFiles/excluded.dir/test.c.o"}]

    def test_header_check_rejects_a_symlinked_object_file(self) -> None:
        entries = self.symlinked_object_file()
        log = self.s.deps_log([f"{OBJ_DIR}/real.c.o", f"{OBJ_DIR}/alias.c.o"])
        failures = self.s.header_failures(entries, self.b(), log)
        self.assertEqual(len(failures), 1)
        self.assertIn("alias.c.o: object path is a symlink", failures[0])

    def test_header_check_rejects_a_symlinked_object_directory(self) -> None:
        entries = self.symlinked_object_dir()
        expected, failures = header_check.select_expected(entries, ["jsref"], self.b())
        self.assertEqual(len(expected), 1, "the object must not drop out of view")
        self.assertEqual(len(failures), 1)
        self.assertIn("goes through a symlink inside the build directory", failures[0])

    def test_baseline_tool_rejects_a_symlinked_object_file(self) -> None:
        entries = self.symlinked_object_file()
        self.assertEqual(len(baseline_tool.untrusted_objects(entries, self.b())), 1)
        (self.s.build / "compile_commands.json").write_text(json.dumps(entries))
        with self.assertRaises(SystemExit) as raised:
            baseline_tool.require_full_build(
                self.s.compile_log([f"{OBJ_DIR}/real.c.o", f"{OBJ_DIR}/alias.c.o"]),
                self.s.build)
        self.assertIn("is a symlink", str(raised.exception))

    def test_baseline_tool_rejects_one_compile_for_two_entries(self) -> None:
        entries = self.symlinked_target_dir()
        (self.s.build / "compile_commands.json").write_text(json.dumps(entries))
        with self.assertRaises(SystemExit) as raised:
            baseline_tool.require_full_build(
                self.s.compile_log(["CMakeFiles/active.dir/test.c.o"]), self.s.build)
        self.assertIn("excluded.dir/test.c.o goes through a symlink", str(raised.exception))

    def test_header_check_rejects_an_object_dir_linked_to_the_build_root(self) -> None:
        """A symlink to the build root itself, deeper in an object path, must
        neither hide the CMakeFiles/<target>.dir part nor pass the check."""
        (self.s.build / "CMakeFiles" / "jsref.dir").mkdir(parents=True)
        (self.s.build / "CMakeFiles" / "jsref.dir" / "js").symlink_to(self.s.build)
        entries = [{"directory": self.b(), "output": f"{OBJ_DIR}/x.c.o"}]
        expected, failures = header_check.select_expected(entries, ["jsref"], self.b())
        self.assertEqual(len(expected), 1, "the object must not drop out of view")
        self.assertEqual(len(failures), 1)
        self.assertIn("goes through a symlink inside the build directory", failures[0])

    def test_generated_header_under_a_symlinked_directory_is_rejected(self) -> None:
        outside = self.top / "outside-generated"
        outside.mkdir()
        (outside / "prcpucfg.h").write_text("/* generated elsewhere */\n")
        (self.s.build / "generated").mkdir()
        (self.s.build / "generated" / "jsref").symlink_to(outside)
        obj = buildpaths.resolve_object(self.s.generated, "/", self.b())
        self.assertEqual(obj.problem, "goes through a symlink inside the build directory")

    def test_both_reject_two_spellings_of_one_object(self) -> None:
        entries = [{"directory": self.b(), "output": f"{OBJ_DIR}/rel.c.o"},
                   {"directory": self.b(), "output": f"./{OBJ_DIR}/rel.c.o"}]
        _, failures = header_check.select_expected(entries, ["jsref"], self.b())
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(baseline_tool.untrusted_objects(entries, self.b())), 1)
        records = header_check.parse_deps_log(
            self.s.deps_log([f"{OBJ_DIR}/rel.c.o", f"{self.b()}/{OBJ_DIR}/rel.c.o"]),
            self.b())
        self.assertEqual(records[os.path.join(self.b(), OBJ_DIR, "rel.c.o")][0], "AMBIGUOUS")

    # --- header identity ----------------------------------------------------

    def header_dep_failures(self, *deps: str) -> list[str]:
        entries = [{"directory": self.b(), "output": f"{OBJ_DIR}/rel.c.o"}]
        log = self.s.deps_log([f"{OBJ_DIR}/rel.c.o"], deps=deps)
        return self.s.header_failures(entries, self.b(), log)

    def test_header_check_accepts_the_real_generated_header(self) -> None:
        self.s.write_headers()
        self.assertEqual(self.header_dep_failures(self.s.generated), [])

    def test_header_check_rejects_the_static_header_symlinked_as_prcpucfg(self) -> None:
        self.s.write_headers()
        os.remove(self.s.static)
        Path(self.s.static).symlink_to(self.s.generated)
        failures = self.header_dep_failures(self.s.static)
        self.assertTrue(any(f"depends on the static {self.s.static}" in f for f in failures))

    def test_header_check_rejects_a_differently_named_link_to_the_static_header(self) -> None:
        self.s.write_headers()
        alias = Path(self.s.static).parent / "alias.h"
        alias.symlink_to(self.s.static)
        failures = self.header_dep_failures(self.s.generated, str(alias))
        self.assertEqual(len(failures), 1)
        self.assertIn(f"depends on the static {alias}", failures[0])

    def test_header_check_rejects_a_hard_link_to_the_static_header(self) -> None:
        self.s.write_headers()
        alias = Path(self.s.static).parent / "review-alias.h"
        os.link(self.s.static, alias)
        failures = self.header_dep_failures(self.s.generated, str(alias))
        self.assertEqual(len(failures), 1)
        self.assertIn(f"depends on the static {alias}", failures[0])

    def test_header_check_rejects_a_generated_header_that_is_a_symlink(self) -> None:
        self.s.write_headers()
        os.remove(self.s.generated)
        Path(self.s.generated).symlink_to(self.s.static)
        failures = self.header_dep_failures(self.s.generated)
        self.assertTrue(any("depends on the static" in f for f in failures), failures)

    # --- build directory location and module shadowing ---------------------

    def test_build_directory_location_does_not_select_a_target(self) -> None:
        nested = self.top / "CMakeFiles" / "jsref.dir" / "nested"
        nested.mkdir(parents=True)
        entries = [{"directory": str(nested), "output": "CMakeFiles/other.dir/x.c.o"}]
        expected, _ = header_check.select_expected(entries, ["jsref"], str(nested))
        self.assertEqual(expected, {})

    def test_canonical_keeps_the_final_component(self) -> None:
        target = self.top / "file.o"
        target.write_bytes(b"x")
        (self.top / "link.o").symlink_to(target)
        self.assertEqual(buildpaths.canonical("link.o", str(self.top)),
                         str(self.top / "link.o"))
        self.assertEqual(buildpaths.canonical(str(self.s.linked / "a.o"), "/"),
                         str(self.s.build / "a.o"))

    def test_tools_directory_does_not_shadow_the_standard_library(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(ROOT / "tools"))
        out = subprocess.run(
            [sys.executable, "-B", "-c",
             "import argparse, shutil, warnings; print(warnings.__file__)"],
            env=env, capture_output=True, text=True, check=True).stdout.strip()
        self.assertNotEqual(Path(out).resolve().parent, (ROOT / "tools").resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
