"""The `baton` command line (specification section 1)."""

import os
import shutil
import subprocess
import sys

from . import __version__
from . import markdown
from . import spec
from .checker import check
from .codegen import generate
from .diagnostics import CompileError, Reporter
from .lexer import lex
from .modules import load_modules
from .parser import parse

USAGE = """usage: baton <command> <file.bt> [options]

commands:
  build FILE.bt      compile to C, then gcc to a binary
  run FILE.bt        build and run
  check FILE.bt      stop after type checking (no gcc)
  man [SECTION]      show the language specification (baton-spec.md)
  libinstall PKG     install a library package
  libs               list installed libraries

options:
  -o FILE            output binary (default: the source name without .bt)
  -W none|error      silence warnings, or make them errors
  --emit-c           with build: write the C and stop before gcc
  --list             with man: list the spec sections and stop
  --raw              with man: print the spec as markdown, not as text
  --no-pager         with man: write the spec straight to stdout
  -h, --help         show this message
  -v, --version      show the version

`baton man` takes a section number or part of a section title, so
`baton man 13` shows "Memory management" and `baton man memory` finds it
too. The specification is markdown, but it is rendered as plain text for
the terminal; `baton man --raw` gives you the markdown itself. Set
BATON_SPEC to point at the specification file if it cannot be found.
"""


def read_source(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().replace("\r\n", "\n")


def compile_to_c(path, warnings):
    source = read_source(path)
    filename = os.path.basename(path)
    reporter = Reporter(filename, source, warnings=warnings)
    try:
        tokens = lex(source, filename)
        program = parse(tokens, source, filename)
        load_modules(program, path)
        check(program, reporter, filename)
    except CompileError as exc:
        reporter.error(exc)
        return None, reporter
    if reporter.failed:
        return None, reporter
    try:
        c_source = generate(program, filename)
    except CompileError as exc:
        reporter.error(exc)
        return None, reporter
    return c_source, reporter


def parse_args(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return None
    if argv[0] in ("-v", "--version"):
        print("baton %s" % __version__)
        return None
    command = argv[0]
    if command not in ("build", "run", "check", "man", "libinstall", "libs"):
        print("baton: unknown command '%s'\n" % command, file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return None
    opts = {"command": command, "output": None, "warnings": "default",
            "emit_c": False, "pager": True, "list": False, "raw": False}
    positional = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "-o":
            i += 1
            if i >= len(argv):
                print("baton: -o needs a file name", file=sys.stderr)
                return None
            opts["output"] = argv[i]
        elif arg == "-W":
            i += 1
            if i >= len(argv) or argv[i] not in ("none", "error", "default"):
                print("baton: -W takes none, error or default", file=sys.stderr)
                return None
            opts["warnings"] = argv[i]
        elif arg == "--emit-c":
            opts["emit_c"] = True
        elif arg == "--no-pager":
            opts["pager"] = False
        elif arg == "--list":
            opts["list"] = True
        elif arg == "--raw":
            opts["raw"] = True
        elif arg.startswith("-"):
            print("baton: unknown option '%s'" % arg, file=sys.stderr)
            return None
        elif positional is not None:
            print("baton: only one source file at a time", file=sys.stderr)
            return None
        else:
            positional = arg
        i += 1
    if command == "man":
        opts["section"] = positional
        return opts
    if command == "libinstall":
        opts["package"] = positional
        return opts
    if command == "libs":
        return opts
    if positional is None:
        print("baton: %s needs a .bt file" % command, file=sys.stderr)
        return None
    opts["file"] = positional
    return opts


def page_width():
    """The width to wrap the specification at."""
    if not sys.stdout.isatty():
        return 80
    return max(60, min(shutil.get_terminal_size((80, 24)).columns, 100))


def page(text, use_pager=True):
    """Show `text` through a pager, or straight to stdout when not a tty."""
    if not use_pager or not sys.stdout.isatty():
        sys.stdout.write(text)
        return 0
    command = (os.environ.get("BATON_PAGER") or os.environ.get("MANPAGER")
               or os.environ.get("PAGER"))
    if command is None:
        if shutil.which("less"):
            command = "less -R"
        elif shutil.which("more"):
            command = "more"
    if command is None:
        sys.stdout.write(text)
        return 0
    env = dict(os.environ)
    env.setdefault("LESS", "FRX")
    try:
        proc = subprocess.Popen(command, shell=True, stdin=subprocess.PIPE,
                                text=True, env=env)
    except OSError:
        sys.stdout.write(text)
        return 0
    proc.communicate(text)
    return proc.returncode


def cmd_man(opts):
    """Show the language specification."""
    path, problem = spec.find_spec()
    if path is None:
        print("baton: cannot find the specification: %s" % problem,
              file=sys.stderr)
        print("baton: set BATON_SPEC to the path of the specification",
              file=sys.stderr)
        return 2
    text = spec.read_spec(path)

    if opts["list"]:
        return page(spec.toc(text), opts["pager"])

    wanted = opts.get("section")
    if wanted:
        matches = spec.match_sections(text, wanted)
        if not matches:
            print("baton: no section matching '%s'" % wanted, file=sys.stderr)
            print("", file=sys.stderr)
            print(spec.toc(text), file=sys.stderr)
            return 2
        if len(matches) > 1:
            print("baton: '%s' matches more than one section:" % wanted,
                  file=sys.stderr)
            for section in matches:
                print("  %2d. %s" % (section["number"], section["title"]),
                      file=sys.stderr)
            return 2
        text = spec.section_text(text, matches[0])

    if opts["raw"]:
        return page(text, opts["pager"])
    return page(markdown.render(text, width=page_width()), opts["pager"])


def lib_dir():
    home = os.path.expanduser("~")
    base = os.path.join(home, ".local", "share", "baton", "lib")
    os.makedirs(base, exist_ok=True)
    return base


def cmd_libinstall(opts):
    pkg = opts.get("package")
    if not pkg:
        print("baton: libinstall needs a package name", file=sys.stderr)
        return 2
    base = lib_dir()
    import urllib.request
    import json
    # Try GitHub raw from commodorial64/baton sharpe or package
    urls = [
        f"https://raw.githubusercontent.com/commodorial64/baton/sharpe/{pkg}/{pkg}.btl",
        f"https://raw.githubusercontent.com/commodorial64/baton/sharpe/{pkg}.btl",
        f"https://raw.githubusercontent.com/commodorial64/baton/main/{pkg}/{pkg}.btl",
        f"https://raw.githubusercontent.com/commodorial64/baton/main/{pkg}.btl",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            outdir = os.path.join(base, pkg)
            os.makedirs(outdir, exist_ok=True)
            outpath = os.path.join(outdir, f"{pkg}.btl")
            with open(outpath, "wb") as f:
                f.write(data)
            print(f"installed {pkg} to {outpath}")
            return 0
        except Exception:
            continue
    print(f"baton: could not find package '{pkg}'", file=sys.stderr)
    return 1


def cmd_libs():
    base = lib_dir()
    if not os.path.exists(base):
        print("(none)")
        return 0
    items = os.listdir(base)
    if not items:
        print("(none)")
        return 0
    for i in sorted(items):
        print(i)
    return 0


def main(argv):
    opts = parse_args(argv)
    if opts is None:
        return 0 if (not argv or argv[0] in ("-h", "--help", "-v", "--version")) else 2

    if opts["command"] == "man":
        return cmd_man(opts)
    if opts["command"] == "libinstall":
        return cmd_libinstall(opts)
    if opts["command"] == "libs":
        return cmd_libs()

    path = opts["file"]
    if not os.path.exists(path):
        print("baton: no such file: %s" % path, file=sys.stderr)
        return 2

    c_source, reporter = compile_to_c(path, opts["warnings"])
    if c_source is None:
        return 1

    stem = os.path.splitext(path)[0]
    c_path = stem + ".c"
    with open(c_path, "w", encoding="utf-8") as handle:
        handle.write(c_source)

    if opts["command"] == "check" or opts["emit_c"]:
        return 0

    binary = opts["output"] or stem
    gcc = shutil.which("gcc")
    if gcc is None:
        print("baton: gcc not found on PATH", file=sys.stderr)
        try:
            os.unlink(c_path)
        except OSError:
            pass
        return 2

    cmd = [gcc, "-std=c11", "-fwrapv", "-O0", "-g", "-o", binary, c_path, "-lm"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("baton: gcc failed:", file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        print("baton: the generated C is at %s" % c_path, file=sys.stderr)
        return 1

    try:
        os.unlink(c_path)
    except OSError:
        pass

    if opts["command"] == "run":
        proc = subprocess.run([binary])
        return proc.returncode
    return 0
