"""Loading for `mod ... get-from` (specification section 19).

`.bt` modules are parsed and merged into the root program.  `.btl` modules are
C headers: their `<module>_name` prototypes become an extern-backed namespace,
and the generated C includes the header.
"""

import os
import re

from . import types as T
from .ast_nodes import Call, FnDecl, Member, MethodCall, Name, NamespaceDecl, Param
from .diagnostics import CompileError
from .lexer import lex
from .parser import parse


_C_TYPES = {
    "int8_t": T.I8, "int16_t": T.I16, "int32_t": T.I32, "int64_t": T.I64 if hasattr(T, "I64") else T.I,
    "uint8_t": T.U8, "uint16_t": T.U16, "uint32_t": T.U32, "uint64_t": T.U64 if hasattr(T, "U64") else T.U,
    "double": T.F, "float": T.F32, "bool": T.B, "char": T.C,
    "baton_str": T.S,
    # common C
    "int": T.I,
    "short": T.I16 if hasattr(T, "I16") else T.I,
    "long": T.I,
    "long long": T.I,
    "signed": T.I,
    "unsigned": T.U,
    "unsigned int": T.U,
    "unsigned short": T.U16 if hasattr(T, "U16") else T.U,
    "unsigned long": T.U,
    "unsigned long long": T.U,
    "size_t": T.U,
    "ssize_t": T.I,
    "void": None,
}

_QUALIFIERS = {"const", "volatile", "static", "extern", "register"}


def lib_dir():
    """Where `baton libinstall` puts packages (BATON_LIB overrides)."""
    env = os.environ.get("BATON_LIB")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".local", "lib", "baton")


_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def version_key(name):
    """Sort key for package versions such as 0.1, 0.2 and 1.10.3."""
    key = []
    for part in re.split(r"[._+-]", name):
        if part.isdigit():
            key.append((0, int(part), ""))
        else:
            key.append((1, 0, part))
    return tuple(key)


def installed_versions(package_root):
    """Version directories installed under one package, oldest first."""
    if not os.path.isdir(package_root):
        return []
    versions = []
    for name in os.listdir(package_root):
        path = os.path.join(package_root, name)
        if name.startswith(".") or name == "latest":
            continue
        if os.path.isdir(path) and _VERSION_RE.match(name):
            versions.append(name)
    return sorted(versions, key=version_key)


def latest_package_dir(package_root):
    """The directory `latest` points at, or the highest installed version."""
    link = os.path.join(package_root, "latest")
    if os.path.isdir(link):
        return os.path.realpath(link)
    versions = installed_versions(package_root)
    if versions:
        return os.path.join(package_root, versions[-1])
    return None


def _strip_comments(text):
    text = re.sub(r"/-.*?/-", "", text, flags=re.S)
    text = re.sub(r"--[^\n]*", "", text)
    return text


def _c_type(text):
    s = " ".join(str(text).split())
    ptrs = s.count("*")
    # remove stars
    t = s.replace("*", " ")
    t = " ".join(t.split())
    # drop qualifiers
    parts = [p for p in t.split() if p not in _QUALIFIERS]
    if not parts:
        return None
    joined = " ".join(parts)
    base = None
    if joined in _C_TYPES:
        base = _C_TYPES[joined]
    elif parts:
        base = _C_TYPES.get(parts[-1])
        if base is None and len(parts) > 1:
            base = _C_TYPES.get(joined)
    if base is T.VOID or joined == "void":
        base = T.VOID
    if base is None:
        # common cases
        if joined in ("char", "unsigned char", "signed char"):
            base = T.C
        elif "void" in joined:
            base = T.I  # map void* to pointer to int/opaque for baton
        elif "char" in joined:
            base = T.C
        elif joined in ("int", "signed int"):
            base = T.I
        elif joined in ("unsigned int", "unsigned"):
            base = T.U if hasattr(T, "U") else T.I
        elif joined in ("float",):
            base = T.F32
        elif joined in ("double",):
            base = T.F
        else:
            return None
    # for void pointer base, prefer pointer to int as opaque handle in baton
    if base == T.VOID and ptrs >= 1:
        base = T.I
    for _ in range(ptrs):
        base = T.pointer_to(base)
    return base


def _split_params(text):
    if not text.strip() or text.strip() == "void":
        return []
    out = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return out


def _parse_btl(path, module_name):
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    # A `.btl` may ask the compiler to pass flags to the linker, e.g.
    #   /* baton:link -lSDL2 */
    link_flags = []
    for flag_match in re.finditer(r"baton:link\s+([^\n*]+)", raw):
        for flag in flag_match.group(1).split():
            if flag.startswith(("-l", "-L", "-Wl,")):
                link_flags.append(flag)
    text = _strip_comments(raw)

    # Keep only declarations at file scope; this deliberately accepts the C
    # subset a baton `.btl` uses and skips anything it cannot map.
    pattern = re.compile(
        r"(?m)^[ \t]*(?!typedef\b|struct\b|enum\b|union\b|#)"
        r"([A-Za-z_][A-Za-z0-9_\s\*]*?)\b([A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\(([^;{}()]*)\)\s*;")
    functions = []
    for match in pattern.finditer(text):
        ret_text, full_name, params_text = match.groups()
        prefix = module_name + "_"
        if not full_name.startswith(prefix) or len(full_name) == len(prefix):
            continue
        member = full_name[len(prefix):]
        ret = _c_type(ret_text)
        if ret is T.VOID:
            ret = None
        if ret is None and ret_text.strip() not in ("void",):
            continue
        params = []
        ok = True
        for i, piece in enumerate(_split_params(params_text)):
            # Last identifier is the parameter name; the rest is its type.
            name_match = re.match(r"^(.*?)([A-Za-z_][A-Za-z0-9_]*)\s*$", piece)
            if name_match:
                type_text, name = name_match.group(1), name_match.group(2)
                type_text = type_text.strip()
                if not type_text:
                    type_text, name = piece, "arg%d" % i
            else:
                type_text, name = piece, "arg%d" % i
            ty = _c_type(type_text)
            if ty is None:
                ok = False
                break
            params.append(Param(ty, name, 1, 1))
        if not ok:
            continue
        rets = [] if ret is None else [ret]
        fn = FnDecl(member, params, ret, None, 1, 1, 1,
                    type_params=[], rets=rets, extern=True, c_name=full_name)
        fn.from_btl = True
        functions.append(fn)
    if not functions:
        raise CompileError("module '%s' exposes no callable C prototypes" % path)
    ns = NamespaceDecl(module_name, [], None, functions, [], 1, 1, 1)
    ns.link_flags = list(dict.fromkeys(link_flags))
    return ns


def _check_expose(program, path):
    stem = os.path.splitext(os.path.basename(path))[0]
    names = []
    for expose in program.exposes:
        names.extend(expose.names)
    if stem not in names:
        raise CompileError("module '%s' must expose '%s'" % (path, stem))
    return names


class ModuleLoader:
    def __init__(self, root_program, root_path):
        self.root = root_program
        self.root_path = os.path.abspath(root_path)
        self.loaded = {self.root_path: ("bt", None)}
        self.stack = [self.root_path]
        self.includes = []
        self.externs = []
        self.link_flags = []

    def run(self):
        self._load_imports(self.root, os.path.dirname(self.root_path))
        self.root.btl_includes = list(dict.fromkeys(self.includes))
        self.root.btl_externs = list(self.externs)
        self.root.btl_link_flags = list(dict.fromkeys(self.link_flags))
        return self.root

    def _resolve_import(self, imp, base_dir):
        if imp.package:
            return self._resolve_package(imp)
        path = imp.path
        if os.path.isabs(path):
            candidate = os.path.normpath(path)
        else:
            candidate = os.path.normpath(os.path.join(base_dir, path))
        if not os.path.isfile(candidate):
            raise CompileError("cannot find module '%s'" % imp.path,
                               imp.line, imp.col, imp.span)
        return candidate

    def _resolve_package(self, imp):
        root = os.path.join(lib_dir(), imp.package)
        if not os.path.isdir(root):
            raise CompileError(
                "package '%s' is not installed under %s (run 'baton libinstall %s')"
                % (imp.package, lib_dir(), imp.package),
                imp.line, imp.col, imp.span)

        if imp.version and imp.version != "latest":
            if not _VERSION_RE.fullmatch(imp.version) or imp.version in (".", ".."):
                raise CompileError("invalid package version '%s'" % imp.version,
                                   imp.line, imp.col, imp.span)
            version_dir = os.path.join(root, imp.version)
            if not os.path.isdir(version_dir):
                versions = installed_versions(root)
                hint = ""
                if versions:
                    hint = "; installed: " + ", ".join(versions)
                raise CompileError(
                    "package '%s' version '%s' is not installed under %s%s"
                    % (imp.package, imp.version, root, hint),
                    imp.line, imp.col, imp.span)
        else:
            version_dir = latest_package_dir(root)
            if version_dir is None:
                raise CompileError(
                    "package '%s' has no installed versions under %s"
                    % (imp.package, root),
                    imp.line, imp.col, imp.span)

        if imp.entry:
            rel = imp.entry.replace("\\", "/")
            base = os.path.normpath(os.path.join(version_dir, *rel.split("/")))
            candidates = [base]
            if not os.path.splitext(base)[1]:
                candidates += [base + ".btl", base + ".bt"]
        else:
            candidates = [os.path.join(version_dir, imp.package + ".btl"),
                          os.path.join(version_dir, imp.package + ".bt")]

        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        if imp.entry:
            wanted = ", ".join(candidates)
        else:
            wanted = "%s.btl or %s.bt" % (imp.package, imp.package)
        raise CompileError(
            "package '%s' has no %s in %s" % (imp.package, wanted, version_dir),
            imp.line, imp.col, imp.span)

    def _load_imports(self, program, base_dir):
        for imp in program.imports:
            path = self._resolve_import(imp, base_dir)
            real = os.path.abspath(path)
            stem, ext = os.path.splitext(os.path.basename(real))
            ext = ext.lower()
            if ext not in (".bt", ".btl"):
                raise CompileError("module '%s' must be .bt or .btl" % imp.path,
                                   imp.line, imp.col, imp.span)
            module_name = stem
            if real in self.stack:
                raise CompileError("module cycle involving '%s'" % imp.path,
                                   imp.line, imp.col, imp.span)
            if real not in self.loaded:
                self.stack.append(real)
                try:
                    if ext == ".bt":
                        source = self._read(real)
                        parsed = parse(lex(source, os.path.basename(real)),
                                       source, os.path.basename(real))
                        names = _check_expose(parsed, real)
                        self._load_imports(parsed, os.path.dirname(real))
                        self._merge(parsed, real, names)
                        self.loaded[real] = ("bt", module_name)
                    else:
                        ns = _parse_btl(real, module_name)
                        self.root.namespaces.append(ns)
                        self.externs.extend(ns.functions)
                        self.link_flags.extend(getattr(ns, "link_flags", []) or [])
                        self.includes.append(real)
                        self.loaded[real] = ("btl", module_name)
                finally:
                    self.stack.pop()
            alias = imp.alias or module_name
            self.root.module_aliases[alias] = module_name
            imp.resolved = real

    @staticmethod
    def _read(path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().replace("\r\n", "\n")

    def _merge(self, module, path, exposed):
        # A .bt module is compiled into the same C translation unit.  Public
        # names are exactly what `expose` lists.  Everything else is renamed
        # with a module prefix, which keeps it private and makes two modules
        # with the same helper name harmless.
        stem = os.path.splitext(os.path.basename(path))[0]
        exposed = set(exposed)
        prefix = "__mod_%s_" % re.sub(r"[^A-Za-z0-9_]", "_", stem)
        fn_names = {fn.name: prefix + fn.name for fn in module.functions
                    if fn.name not in exposed and fn.name != "main"}
        ns_names = {ns.name: prefix + ns.name for ns in module.namespaces
                    if ns.name not in exposed}
        struct_names = {s.name: prefix + s.name for s in module.structs
                        if s.name not in exposed}
        global_names = {g.names[0]: prefix + g.names[0] for g in module.globals
                        if g.names and g.names[0] not in exposed}

        def rename_type(ty):
            if ty is None:
                return
            if ty.kind == "named" and ty.name_ in struct_names:
                ty.name_ = struct_names[ty.name_]
            elif ty.kind == "struct":
                if ty.name_ in struct_names:
                    ty.name_ = struct_names[ty.name_]
                for arg in ty.args:
                    rename_type(arg)
            elif ty.kind == "pointer":
                rename_type(ty.elem)
            elif ty.kind == "array":
                rename_type(ty.elem)
            elif ty.kind == "list":
                rename_type(ty.elem)
            elif ty.kind == "tuple":
                for elem in ty.elems:
                    rename_type(elem)

        def walk(obj, seen=None):
            if seen is None:
                seen = set()
            if obj is None or isinstance(obj, (str, int, float, bool, bytes)):
                return
            if isinstance(obj, T.Ty):
                rename_type(obj)
                return
            oid = id(obj)
            if oid in seen:
                return
            seen.add(oid)
            if isinstance(obj, (list, tuple)):
                for item in obj:
                    walk(item, seen)
                return
            if isinstance(obj, dict):
                for item in obj.values():
                    walk(item, seen)
                return
            if isinstance(obj, Name):
                if obj.name in global_names:
                    obj.name = global_names[obj.name]
                if "." in obj.name:
                    head, _, tail = obj.name.partition(".")
                    if head in ns_names:
                        obj.name = "%s.%s" % (ns_names[head], tail)
            elif isinstance(obj, Call):
                if "." in obj.name:
                    head, _, tail = obj.name.partition(".")
                    if head in ns_names:
                        obj.name = "%s.%s" % (ns_names[head], tail)
                elif obj.name in fn_names:
                    obj.name = fn_names[obj.name]
                elif obj.name in struct_names:
                    # alloc(TYPE, n) stores the type as a name expression.
                    obj.name = struct_names[obj.name]
            elif isinstance(obj, MethodCall):
                if isinstance(obj.obj, Name):
                    if obj.obj.name in ns_names:
                        obj.obj.name = ns_names[obj.obj.name]
                    elif obj.obj.name in global_names:
                        obj.obj.name = global_names[obj.obj.name]
            elif isinstance(obj, Member):
                if isinstance(obj.obj, Name):
                    if obj.obj.name in ns_names:
                        obj.obj.name = ns_names[obj.obj.name]
                    elif obj.obj.name in global_names:
                        obj.obj.name = global_names[obj.obj.name]
            if hasattr(obj, "__dict__"):
                for value in vars(obj).values():
                    walk(value, seen)

        for fn in module.functions:
            if fn.name == "main":
                continue
            walk(fn)
            if fn.name in fn_names:
                fn.name = fn_names[fn.name]
        for ns in module.namespaces:
            walk(ns)
            if ns.name in ns_names:
                ns.name = ns_names[ns.name]
            for fn in ns.functions:
                if getattr(fn, "namespace", None) in ns_names:
                    fn.namespace = ns_names[fn.namespace]
        for s in module.structs:
            walk(s)
            if s.name in struct_names:
                s.name = struct_names[s.name]
        for g in module.globals:
            walk(g)
            if g.names and g.names[0] in global_names:
                g.names[0] = global_names[g.names[0]]

        for g in module.globals:
            self.root.globals.append(g)
        for s in module.structs:
            self.root.structs.append(s)
        for fn in module.functions:
            if fn.name == "main":
                continue
            self.root.functions.append(fn)
        for ns in module.namespaces:
            self.root.namespaces.append(ns)
        for key, value in getattr(module, "module_aliases", {}).items():
            self.root.module_aliases.setdefault(key, value)


def load_modules(program, path):
    return ModuleLoader(program, path).run()
