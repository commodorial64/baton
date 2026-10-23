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
    "int8_t": T.I8, "int16_t": T.I16, "int32_t": T.I32, "int64_t": T.I,
    "uint8_t": T.U8, "uint16_t": T.U16, "uint32_t": T.U32, "uint64_t": T.U,
    "double": T.F, "float": T.F32, "bool": T.B, "char": T.C,
    "baton_str": T.S,
}

_QUALIFIERS = {"const", "volatile", "static", "extern", "register"}


def _strip_comments(text):
    text = re.sub(r"/-.*?/-", "", text, flags=re.S)
    text = re.sub(r"--[^\n]*", "", text)
    return text


def _c_type(text):
    text = " ".join(text.split())
    ptrs = 0
    while text.endswith("*"):
        ptrs += 1
        text = text[:-1].strip()
    parts = [p for p in text.replace("*", " ").split() if p not in _QUALIFIERS]
    if not parts:
        return None
    base = _C_TYPES.get(parts[-1])
    if base is None:
        return None
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
        text = _strip_comments(handle.read())
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
                if not type_text or type_text.endswith("*"):
                    type_text = type_text + " " + name
                    name = "arg%d" % i
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
        functions.append(fn)
    if not functions:
        raise CompileError("module '%s' exposes no callable C prototypes" % path)
    return NamespaceDecl(module_name, [], None, functions, [], 1, 1, 1)


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

    def run(self):
        self._load_imports(self.root, os.path.dirname(self.root_path))
        self.root.btl_includes = list(dict.fromkeys(self.includes))
        self.root.btl_externs = list(self.externs)
        return self.root

    def _load_imports(self, program, base_dir):
        for imp in program.imports:
            path = imp.path
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(base_dir, path))
            if not os.path.exists(path):
                raise CompileError("cannot find module '%s'" % imp.path,
                                   imp.line, imp.col, imp.span)
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
