"""Object and header identity for the build verification scripts.

The sources the scripts compare spell paths differently:

- compile_commands.json "output" is relative to the entry's "directory" with
  CMake 3.x, but absolute with CMake 4.x;
- Ninja (its deps log and its "Building C object" status lines) names
  objects relative to the build directory.

So every path is resolved against its own base. Aliases of the build
directory itself (a symlinked build dir, "..") compare equal. Below the
build directory, CMake and Ninja never create symlinks, so an object path
that goes through one is rejected rather than resolved: a symlink there
could make one object stand in for another, or move an object out of view.
A path that does not exist still resolves, so a genuinely missing object
stays missing.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, NamedTuple, Optional


def canonical(path: str, base: str) -> str:
    """`path` (absolute, or relative to `base`) with symlinks and ".." resolved
    in its directory part; the final component keeps its own name."""
    head, tail = os.path.split(os.path.join(base, path))
    return os.path.join(os.path.realpath(head), tail)


def is_same_file(path: str, expected: str) -> bool:
    """`path` (absolute) is the real file `expected`, both as spelled (directory
    part resolved) and physically (no symlink standing in for it)."""
    return canonical(path, "/") == expected and os.path.realpath(path) == expected


def names_file(path: str, name: str) -> bool:
    """`path` (absolute) is called `name`, or resolves to a file called `name`
    (so a differently named symlink to it is recognized too)."""
    return (os.path.basename(path) == name
            or os.path.basename(os.path.realpath(path)) == name)


def same_inode(a: str, b: str) -> bool:
    """`a` and `b` are the same file on disk (device and inode), so a hard
    link under any name is recognized. False if either does not exist."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


class ObjectPath(NamedTuple):
    path: str               # canonical path, used as the object's identity
    spelled: str            # as written, joined to its base (for messages)
    rel: Optional[str]      # lexical path below the build directory, or None
    problem: Optional[str]  # why the path cannot be trusted, or None


def _below_build_dir(lexical: str, root: str) -> Optional[str]:
    """The part of `lexical` below its outermost ancestor that is (an alias
    of) `root`. Outermost, so that a symlink to the build root deeper in the
    path cannot hide the components above it (e.g. CMakeFiles/<target>.dir)."""
    found = None
    ancestor = os.path.dirname(lexical)
    while True:
        if os.path.realpath(ancestor) == root:
            found = ancestor
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            break
        ancestor = parent
    return None if found is None else os.path.relpath(lexical, found)


def resolve_object(path: str, base: str, build_dir: str) -> ObjectPath:
    root = os.path.realpath(build_dir)
    spelled = os.path.join(base, path)
    resolved = canonical(path, base)
    rel = _below_build_dir(os.path.normpath(spelled), root)
    if rel is None:
        problem = "is outside the build directory"
    elif resolved != os.path.join(root, rel):
        problem = "goes through a symlink inside the build directory"
    elif os.path.islink(resolved):
        problem = "is a symlink"
    else:
        problem = None
    return ObjectPath(resolved, spelled, rel, problem)


def entry_object(entry: dict, build_dir: str) -> ObjectPath:
    """The object of a compile_commands.json entry."""
    return resolve_object(entry["output"], entry["directory"], build_dir)


def ninja_path(path: str, build_dir: str) -> str:
    """Canonical form of a path as Ninja reports it (relative to the build dir)."""
    return canonical(path, build_dir)


def target_of(rel: Optional[str], targets: Iterable[str]) -> Optional[str]:
    """The target whose object directory holds the build-relative path `rel`.
    Judged before any symlink is resolved, and only below the build
    directory, so neither a symlink nor the build directory's own location
    can change the answer."""
    if rel is None:
        return None
    for target in targets:
        if re.search(rf"(^|/)CMakeFiles/{re.escape(target)}\.dir/", rel):
            return target
    return None
