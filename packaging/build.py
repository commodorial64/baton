#!/usr/bin/env python3
"""Assemble the yapm package for baton and build it.

The package is a staging tree that `yapm build` turns into a .yapm archive:

    dist/baton-<version>/
        yapm.data         the manifest
        run/baton         the launcher, linked into /usr/local/bin
        lib/baton/        the compiler
        share/baton/      the specification and the sample programs
        man/baton.1       the manual page
        uninstall.sh      removes what the package put outside its own tree

Usage:
    python3 packaging/build.py            stage the tree and build the package
    python3 packaging/build.py --stage    stage the tree only
"""

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

VERSION = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
MANIFEST_VERSION = re.compile(r'^version\s*=.*$', re.MULTILINE)


def version():
    """The version the compiler reports."""
    path = os.path.join(ROOT, "baton", "__init__.py")
    with open(path, encoding="utf-8") as handle:
        match = VERSION.search(handle.read())
    if not match:
        sys.exit("baton: no __version__ in baton/__init__.py")
    return match.group(1)


def copy_tree(source, destination, keep=None):
    """Copy a tree, leaving out caches and, with `keep`, other junk."""
    ignored = ["__pycache__", "*.pyc"]

    def ignore(directory, names):
        skip = set()
        for name in names:
            path = os.path.join(directory, name)
            if any(fnmatch.fnmatch(name, pattern) for pattern in ignored):
                skip.add(name)
            elif keep is not None and os.path.isfile(path):
                if not any(name.endswith(suffix) for suffix in keep):
                    skip.add(name)
        return skip

    shutil.copytree(source, destination, ignore=ignore, dirs_exist_ok=True)


def stage(name, ver):
    """Build the package source tree and return its path."""
    target = os.path.join(DIST, "%s-%s" % (name, ver))
    if os.path.exists(target):
        shutil.rmtree(target)
    os.makedirs(target)

    # the compiler
    copy_tree(os.path.join(ROOT, "baton"), os.path.join(target, "lib", "baton"))

    # the specification and the sample programs
    share = os.path.join(target, "share", "baton")
    os.makedirs(share)
    shutil.copy2(os.path.join(ROOT, "baton-spec.md"), share)
    copy_tree(os.path.join(ROOT, "examples"), os.path.join(share, "examples"),
              keep=(".bt", ".c"))

    # the launcher, the manual page and the uninstall script
    copy_tree(os.path.join(HERE, "run"), os.path.join(target, "run"))
    copy_tree(os.path.join(HERE, "man"), os.path.join(target, "man"))
    shutil.copy2(os.path.join(HERE, "uninstall.sh"), target)

    # the manifest, carrying the version the compiler reports
    with open(os.path.join(HERE, "yapm.data"), encoding="utf-8") as handle:
        manifest = handle.read()
    manifest = MANIFEST_VERSION.sub('version = "%s"' % ver, manifest, count=1)
    with open(os.path.join(target, "yapm.data"), "w", encoding="utf-8") as handle:
        handle.write(manifest)

    for script in ("run/baton", "uninstall.sh"):
        os.chmod(os.path.join(target, script), 0o755)

    return target


def build(target, yapm):
    """Turn the staged tree into a .yapm file."""
    os.makedirs(DIST, exist_ok=True)
    command = [yapm, "build", target]
    if os.geteuid() != 0:
        command = ["sudo"] + command
    print("running: %s" % " ".join(command))
    if subprocess.run(command, cwd=DIST).returncode != 0:
        return 1
    # yapm builds the archive through a temp file, so it lands as 0600
    for entry in os.listdir(DIST):
        if entry.endswith(".yapm"):
            os.chmod(os.path.join(DIST, entry), 0o644)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true",
                        help="stage the package tree without building it")
    parser.add_argument("--yapm", default="yapm", help="the yapm command to use")
    opts = parser.parse_args()

    ver = version()
    target = stage("baton", ver)
    print("staged %s" % target)
    if opts.stage:
        return 0
    return build(target, opts.yapm)


if __name__ == "__main__":
    sys.exit(main())
