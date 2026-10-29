"""The `baton` command line (specification section 1)."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

from . import __version__
from . import markdown
from . import spec
from .checker import check
from .codegen import generate
from .diagnostics import CompileError, Reporter
from .lexer import lex
from .modules import installed_versions, latest_package_dir, lib_dir, load_modules
from .parser import parse

USAGE = """usage: baton <command> <file.bt> [options]

commands:
  build FILE.bt      compile to C, then gcc to a binary
  run FILE.bt        build and run
  check FILE.bt      stop after type checking (no gcc)
  man [SECTION]      show the language specification (baton-spec.md)
  libinstall PKG[@VERSION]  install a library package
  libs               list installed libraries and versions

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
        return None, reporter, None
    if reporter.failed:
        return None, reporter, None
    try:
        c_source = generate(program, filename)
    except CompileError as exc:
        reporter.error(exc)
        return None, reporter, None
    return c_source, reporter, program


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


_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def split_package_spec(text):
    """Split `pkg` or `pkg@version`; a leading v on the version is dropped."""
    pkg, sep, version = text.partition("@")
    if sep and not version:
        raise ValueError("version missing after '@'")
    if not _PACKAGE_RE.fullmatch(pkg):
        raise ValueError("invalid package name '%s'" % pkg)
    if version and not _VERSION_RE.fullmatch(version):
        raise ValueError("invalid package version '%s'" % version)
    if version and version.startswith("v") and len(version) > 1:
        version = version[1:]
    return pkg, (version or None)


def _safe_relative(name):
    rel = str(name).replace("\\", "/")
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _install_refs(version):
    """Refs to try, as (ref, is_branch_fallback) pairs."""
    if version is None or version == "latest":
        return [("sharpe", False), ("main", False)]
    refs = ["v" + version, version, "sharpe", "main"]
    return [(ref, ref in ("sharpe", "main"))
            for ref in dict.fromkeys(refs)]


def _point_latest(pkg_root, version):
    """Make `latest` point at the newest installed version."""
    latest = os.path.join(pkg_root, "latest")
    if version == "latest":
        if os.path.islink(latest):
            os.unlink(latest)
        return
    versions = installed_versions(pkg_root)
    if not versions:
        return
    target = versions[-1]
    if os.path.islink(latest):
        if os.path.basename(os.path.realpath(latest)) == target:
            return
        os.unlink(latest)
    elif os.path.isdir(latest):
        shutil.rmtree(latest)
    elif os.path.lexists(latest):
        os.unlink(latest)
    try:
        os.symlink(target, latest)
    except OSError:
        pass


def cmd_libinstall(opts):
    spec = opts.get("package")
    if not spec:
        print("baton: libinstall needs a package name", file=sys.stderr)
        return 2
    try:
        pkg, version = split_package_spec(spec)
    except ValueError as exc:
        print("baton: %s" % exc, file=sys.stderr)
        return 2

    base = lib_dir()
    os.makedirs(base, exist_ok=True)
    repo = "https://api.github.com/repos/commodorial64/baton"
    raw_root = "https://raw.githubusercontent.com/commodorial64/baton"

    def fetch(url):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "baton"})
            with urllib.request.urlopen(request, timeout=30) as resp:
                return resp.read()
        except Exception:
            return None

    def resolve(ref):
        # Pin to a commit so raw.githubusercontent.com cannot serve a stale
        # branch cache after a push.  Fall back to the ref name offline.
        data = fetch("%s/commits/%s" % (repo, urllib.parse.quote(ref, safe="")))
        if data is None:
            return ref
        try:
            return json.loads(data)["sha"]
        except Exception:
            return ref

    def install_from(directory, ref, commit, fallback):
        primary = None
        primary_name = None
        for name in (pkg + ".btl", pkg + ".bt"):
            data = fetch("%s/%s" % (directory, name))
            if data is not None:
                primary = data
                primary_name = name
                break
        if primary is None:
            return None

        manifest = {}
        manifest_data = fetch("%s/package.json" % directory)
        if manifest_data is not None:
            try:
                loaded = json.loads(manifest_data.decode("utf-8"))
                if isinstance(loaded, dict):
                    manifest = loaded
            except Exception:
                manifest = {}
        if manifest.get("name") and manifest["name"] != pkg:
            return None

        target_version = version
        if target_version is None:
            target_version = str(manifest.get("version") or "latest")
        if not _VERSION_RE.fullmatch(target_version):
            return None
        if fallback and version:
            declared = manifest.get("version")
            if declared is not None and str(declared) != target_version:
                return None

        names = []
        if isinstance(manifest.get("files"), list):
            names.extend(str(name) for name in manifest["files"])
        names.extend([primary_name, "constants.bt", pkg + ".c", "package.json"])

        pkg_root = os.path.join(base, pkg)
        os.makedirs(pkg_root, exist_ok=True)
        outdir = os.path.join(pkg_root, target_version)
        tmp = tempfile.mkdtemp(prefix=".install-", dir=pkg_root)
        installed = []
        try:
            for name in dict.fromkeys(names):
                rel = _safe_relative(name)
                if rel is None:
                    continue
                data = primary if rel == primary_name else fetch("%s/%s" % (directory, rel))
                if data is None:
                    continue
                dest = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as handle:
                    handle.write(data)
                installed.append(rel)
            meta = {
                "name": pkg,
                "version": target_version,
                "ref": ref,
                "commit": commit,
                "files": installed,
            }
            with open(os.path.join(tmp, ".baton-package.json"), "w", encoding="utf-8") as handle:
                json.dump(meta, handle, indent=2, sort_keys=True)
                handle.write("\n")
            if os.path.islink(outdir) or os.path.isfile(outdir):
                os.unlink(outdir)
            elif os.path.isdir(outdir):
                shutil.rmtree(outdir)
            os.replace(tmp, outdir)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        _point_latest(pkg_root, target_version)
        warn = bool(fallback and version and manifest.get("version") is None)
        return ("installed %s %s to %s (%s)"
                % (pkg, target_version, outdir, ", ".join(installed)), warn)

    refs = _install_refs(version)
    for ref, fallback in refs:
        commit = resolve(ref)
        root = "%s/%s" % (raw_root, commit)
        for directory in ("%s/%s" % (root, pkg), root):
            result = install_from(directory, ref, commit, fallback)
            if result is not None:
                message, warn = result
                if warn:
                    print("baton: warning: no tag for %s %s; installed %s"
                          % (pkg, version, ref), file=sys.stderr)
                print(message)
                return 0

    tried = ", ".join(ref for ref, _ in refs)
    if version:
        print("baton: could not find package '%s' version '%s' (tried %s)"
              % (pkg, version, tried), file=sys.stderr)
    else:
        print("baton: could not find package '%s'" % pkg, file=sys.stderr)
    return 1


def cmd_libs():
    base = lib_dir()
    if not os.path.exists(base):
        print("(none)")
        return 0
    items = [name for name in sorted(os.listdir(base))
             if os.path.isdir(os.path.join(base, name))]
    if not items:
        print("(none)")
        return 0
    for pkg in items:
        root = os.path.join(base, pkg)
        versions = installed_versions(root)
        latest = latest_package_dir(root)
        latest_name = os.path.basename(latest) if latest else None
        if versions:
            shown = [version + (" (latest)" if version == latest_name else "")
                     for version in versions]
            print("%s  %s" % (pkg, ", ".join(shown)))
        elif latest_name:
            print("%s  latest" % pkg)
        else:
            print(pkg)
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

    c_source, reporter, program = compile_to_c(path, opts["warnings"])
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

    link_flags = list(getattr(program, "btl_link_flags", []) or [])
    cmd = [gcc, "-std=c11", "-fwrapv", "-O0", "-g", "-o", binary, c_path, "-lm"]
    cmd.extend(link_flags)
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
