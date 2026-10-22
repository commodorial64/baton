#!/usr/bin/env python3
"""Test runner for the baton compiler.

Each test lives in a ``.bt`` file with a companion ``.expect`` file:

    <name>.bt        the program
    <name>.expect    expected stdout for a run test
    <name>.err       expected ``baton: ...`` diagnostics for a compile-error test

A ``.bt`` with a ``.expect`` is built and run; its stdout must match exactly.
A ``.bt`` with a ``.err`` must fail to compile, and every line of ``.err`` must
appear in the compiler's stderr. ``.err`` lines beginning with ``#`` are
comments and ignored, so a file may be empty (just fail).
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BATON = [sys.executable, "-m", "baton"]
# BATON_BIN=/path/to/frozen/baton runs the suite against a compiled binary.
if os.environ.get("BATON_BIN"):
    BATON = [os.environ["BATON_BIN"]]

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def cases():
    names = []
    for entry in sorted(os.listdir(HERE)):
        if entry.endswith(".bt"):
            names.append(entry[:-3])
    return names


def read(path):
    with open(path) as handle:
        return handle.read()


def normalise(text):
    return re.sub(r"[ \t]+$", "", text, flags=re.M).strip("\n")


def run_case(name):
    bts = os.path.join(HERE, name + ".bt")
    expect_path = os.path.join(HERE, name + ".expect")
    err_path = os.path.join(HERE, name + ".err")
    warn_path = os.path.join(HERE, name + ".warn")

    if os.path.exists(warn_path):
        proc = subprocess.run(BATON + ["build", bts, "-o",
                                       os.path.join(HERE, ".build", name)],
                              cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, "build failed:\n" + proc.stderr.strip()
        combined = proc.stdout + proc.stderr
        for line in read(warn_path).split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line not in combined:
                return False, "missing warning: %s\n--- got ---\n%s" % (
                    line, combined.strip())
        quiet = subprocess.run(
            BATON + ["build", bts, "-o", os.path.join(HERE, ".build", name),
                     "-W", "none"], cwd=ROOT, capture_output=True, text=True)
        if quiet.stdout.strip() or quiet.stderr.strip():
            return False, "-W none still printed:\n%s" % (
                (quiet.stdout + quiet.stderr).strip())
        return True, "warned, and -W none was silent"

    if os.path.exists(expect_path):
        out = os.path.join(HERE, ".build", name)
        proc = subprocess.run(
            BATON + ["build", bts, "-o", out, "-W", "error"],
            cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, "build failed:\n" + proc.stderr.strip()
        run = subprocess.run([out], cwd=ROOT, capture_output=True, text=True)
        stdin_path = os.path.join(HERE, name + ".in")
        if os.path.exists(stdin_path):
            run = subprocess.run([out], cwd=ROOT, capture_output=True, text=True,
                                 input=read(stdin_path))
        got = normalise(run.stdout)
        want = normalise(read(expect_path))
        if run.returncode != 0 and not os.path.exists(
                os.path.join(HERE, name + ".exit")):
            return False, "exited with %d\n%s" % (run.returncode, run.stderr)
        if got != want:
            return False, "stdout mismatch\n--- want ---\n%s\n--- got ---\n%s" % (
                want, got)
        exit_path = os.path.join(HERE, name + ".exit")
        if os.path.exists(exit_path):
            want_code = int(read(exit_path).strip())
            if run.returncode != want_code:
                return False, "exit code %d, want %d" % (run.returncode, want_code)
        return True, "ran, %d line%s of output" % (
            len(want.split("\n")) if want else 0, "" if want == "" else "s")

    if os.path.exists(err_path):
        proc = subprocess.run(BATON + ["build", bts, "-W", "error"],
                              cwd=ROOT, capture_output=True, text=True)
        if proc.returncode == 0:
            return False, "expected a compile error, but it built"
        combined = proc.stdout + proc.stderr
        for line in read(err_path).split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line not in combined:
                return False, "missing diagnostic: %s\n--- got ---\n%s" % (
                    line, combined.strip())
        return True, "rejected as expected"

    return False, "no .expect or .err file"


def main():
    os.makedirs(os.path.join(HERE, ".build"), exist_ok=True)
    names = cases()
    failures = 0
    for name in names:
        passed, detail = run_case(name)
        if passed:
            print("%sok%s   %-24s %s%s%s" % (GREEN, RESET, name, DIM, detail, RESET))
        else:
            failures += 1
            print("%sFAIL%s %-24s %s" % (RED, RESET, name, detail))
    print()
    print("%d/%d passed" % (len(names) - failures, len(names)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
