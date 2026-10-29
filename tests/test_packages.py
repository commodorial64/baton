import os
import urllib.parse

import pytest

from baton.cli import (_install_refs, _point_latest, cmd_libinstall, cmd_libs,
                       split_package_spec)
from baton.diagnostics import CompileError
from baton.lexer import lex
from baton.modules import load_modules
from baton.parser import parse


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def load(source, tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_LIB", str(tmp_path / "lib"))
    program = parse(lex(source, "main.bt"), source, "main.bt")
    load_modules(program, str(tmp_path / "main.bt"))
    return program


def test_package_version_is_parsed_inside_and_outside_the_brackets():
    source = "mod s get-from <sharpe>@0.2\nmod t get-from <sharpe@0.1>\n"
    program = parse(lex(source, "main.bt"), source, "main.bt")
    first, second = program.imports
    assert (first.package, first.version, first.entry) == ("sharpe", "0.2", None)
    assert (second.package, second.version, second.entry) == ("sharpe", "0.1", None)


def test_package_subpath_is_kept_for_the_loader():
    source = "mod c get-from <sharpe/constants.bt>@0.2\n"
    program = parse(lex(source, "main.bt"), source, "main.bt")
    imp, = program.imports
    assert imp.package == "sharpe"
    assert imp.version == "0.2"
    assert imp.entry == "constants.bt"


def test_latest_package_uses_newest_installed_version(tmp_path, monkeypatch):
    lib = tmp_path / "lib" / "demo"
    write(str(lib / "0.9" / "demo.btl"), "int64_t demo_old(void);\n")
    write(str(lib / "0.10" / "demo.btl"), "int64_t demo_new(void);\n")

    program = load("mod d get-from <demo>\n", tmp_path, monkeypatch)
    assert program.imports[0].resolved == str(lib / "0.10" / "demo.btl")
    assert [fn.name for fn in program.namespaces[0].functions] == ["new"]


def test_latest_symlink_wins_over_version_sort(tmp_path, monkeypatch):
    lib = tmp_path / "lib" / "demo"
    write(str(lib / "0.9" / "demo.btl"), "int64_t demo_old(void);\n")
    write(str(lib / "0.10" / "demo.btl"), "int64_t demo_new(void);\n")
    os.symlink("0.9", str(lib / "latest"))

    program = load("mod d get-from <demo>\n", tmp_path, monkeypatch)
    assert program.imports[0].resolved == str(lib / "0.9" / "demo.btl")


def test_explicit_package_version_and_entry(tmp_path, monkeypatch):
    lib = tmp_path / "lib" / "demo"
    write(str(lib / "0.1" / "demo.btl"), "int64_t demo_one(void);\n")
    write(str(lib / "0.2" / "demo.btl"), "int64_t demo_two(void);\n")
    write(str(lib / "0.2" / "extra.btl"), "int64_t extra_thing(void);\n")

    program = load("mod d get-from <demo>@0.1\nmod e get-from <demo/extra.btl>@0.2\n",
                   tmp_path, monkeypatch)
    assert program.imports[0].resolved == str(lib / "0.1" / "demo.btl")
    assert program.imports[1].resolved == str(lib / "0.2" / "extra.btl")
    assert [fn.name for fn in program.namespaces[1].functions] == ["thing"]


def test_bt_package_can_import_a_relative_helper(tmp_path, monkeypatch):
    package = tmp_path / "lib" / "demo" / "1.0"
    write(str(package / "helper.bt"), """
        ns helper {
            functions {
                twice(i x) { return x * 2 }
            }
        }
        expose helper
    """)
    write(str(package / "demo.bt"), """
        mod h get-from "helper.bt"
        ns demo {
            functions {
                double() { return h.twice(21) }
            }
        }
        expose demo
    """)

    program = load("mod d get-from <demo>\n", tmp_path, monkeypatch)
    assert program.imports[0].resolved == str(package / "demo.bt")
    names = [ns.name for ns in program.namespaces]
    assert "helper" in names and "demo" in names


def test_quoted_paths_are_not_looked_up_as_packages(tmp_path, monkeypatch):
    lib = tmp_path / "lib" / "demo"
    write(str(lib / "1.0" / "demo.btl"), "int64_t demo_go(void);\n")

    with pytest.raises(CompileError):
        load('mod d get-from "demo/demo.btl"\n', tmp_path, monkeypatch)


def test_quoted_paths_are_relative_to_the_importing_file(tmp_path, monkeypatch):
    write(str(tmp_path / "localmod.bt"), """
        ns localmod {
            functions {
                ping() { return 1 }
            }
        }
        expose localmod
    """)

    program = load('mod l get-from "./localmod.bt"\n', tmp_path, monkeypatch)
    assert program.imports[0].resolved == str(tmp_path / "localmod.bt")


def test_missing_package_version_reports_the_version(tmp_path, monkeypatch):
    lib = tmp_path / "lib" / "demo"
    write(str(lib / "0.1" / "demo.btl"), "int64_t demo_one(void);\n")

    with pytest.raises(CompileError, match="version '0.2' is not installed"):
        load("mod d get-from <demo>@0.2\n", tmp_path, monkeypatch)


def test_cli_specs_and_refs():
    assert split_package_spec("sharpe") == ("sharpe", None)
    assert split_package_spec("sharpe@0.2") == ("sharpe", "0.2")
    assert split_package_spec("sharpe@v0.2") == ("sharpe", "0.2")
    with pytest.raises(ValueError):
        split_package_spec("sharpe@")
    with pytest.raises(ValueError):
        split_package_spec("../sharpe")

    assert _install_refs(None) == [("sharpe", False), ("main", False)]
    assert _install_refs("0.2") == [
        ("v0.2", False), ("0.2", False), ("sharpe", True), ("main", True)]


def test_point_latest_keeps_the_newest_version(tmp_path):
    root = tmp_path / "demo"
    (root / "0.1").mkdir(parents=True)
    (root / "0.2").mkdir()
    (root / "1.0").mkdir()

    _point_latest(str(root), "0.2")
    assert os.path.islink(str(root / "latest"))
    assert os.path.basename(os.path.realpath(str(root / "latest"))) == "1.0"

    _point_latest(str(root), "0.1")
    assert os.path.basename(os.path.realpath(str(root / "latest"))) == "1.0"


class _Response:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_github(monkeypatch, refs, files):
    def urlopen(request, timeout=30):
        url = request.full_url
        if "/commits/" in url:
            ref = urllib.parse.unquote(url.rsplit("/commits/", 1)[1])
            if ref not in refs:
                raise OSError("not found")
            return _Response(('{"sha": "%s"}' % refs[ref]).encode())
        marker = "raw.githubusercontent.com/commodorial64/baton/"
        path = url.split(marker, 1)[1]
        sha, _, rel = path.partition("/")
        data = files.get((sha, rel))
        if data is None:
            raise OSError("not found")
        return _Response(data)

    monkeypatch.setattr("baton.cli.urllib.request.urlopen", urlopen)


def test_libinstall_installs_a_versioned_package(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BATON_LIB", str(tmp_path / "lib"))
    files = {
        ("tagsha", "demo/demo.btl"): b"int64_t demo_go(void);\n",
        ("tagsha", "demo/constants.bt"): b"int64_t constants_x(void);\n",
        ("tagsha", "demo/package.json"): (
            b'{"name": "demo", "version": "1.0", "files": ["demo.btl", "constants.bt"]}'
        ),
    }
    fake_github(monkeypatch, {"v1.0": "tagsha", "1.0": "tagsha"}, files)

    assert cmd_libinstall({"package": "demo@1.0"}) == 0
    target = tmp_path / "lib" / "demo" / "1.0"
    assert (target / "demo.btl").is_file()
    assert (target / "constants.bt").is_file()
    assert (target / ".baton-package.json").is_file()
    latest = tmp_path / "lib" / "demo" / "latest"
    assert os.path.islink(str(latest))
    assert os.path.basename(os.path.realpath(str(latest))) == "1.0"
    assert "installed demo 1.0" in capsys.readouterr().out


def test_libinstall_falls_back_to_a_branch_with_a_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BATON_LIB", str(tmp_path / "lib"))
    files = {
        ("branchsha", "demo/demo.btl"): b"int64_t demo_go(void);\n",
    }
    fake_github(monkeypatch,
                {"v2.0": "tagsha", "2.0": "tagsha", "sharpe": "branchsha"},
                files)

    assert cmd_libinstall({"package": "demo@2.0"}) == 0
    target = tmp_path / "lib" / "demo" / "2.0"
    assert (target / "demo.btl").is_file()
    captured = capsys.readouterr()
    assert "warning" in captured.err
    assert "installed demo 2.0" in captured.out


def test_libs_lists_versions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BATON_LIB", str(tmp_path / "lib"))
    (tmp_path / "lib" / "demo" / "0.1").mkdir(parents=True)
    (tmp_path / "lib" / "demo" / "0.2").mkdir()
    os.symlink("0.2", str(tmp_path / "lib" / "demo" / "latest"))

    assert cmd_libs() == 0
    assert "demo  0.1, 0.2 (latest)" in capsys.readouterr().out
