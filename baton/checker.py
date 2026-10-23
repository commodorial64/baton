"""Type checking (specification sections 3 through 26)."""

import copy

from . import types as T
from .ast_nodes import (
    AddrOf, Assign, Binary, Block, BoolLit, BraceLit, Break, Call, Cast, CharLit,
    Continue, Deref, ExprStmt, FloatLit, FnDecl, ForEach, ForRange, If, Index,
    IntLit, Loop, Match, MatchArm, Member, MethodCall, Name, NamespaceDecl,
    RangePattern, Return, Slice, StrLit, StructDecl, Unary, VarDecl, While,
)
from .diagnostics import CompileError

# -- builtins ------------------------------------------------------------
# kind: "print" | "write" | "input" | "panic" | "to" | "try" | "list" | ...
BUILTINS = {
    "print": "print",
    "write": "write",
    "input": "input",
    "panic": "panic",
    "tos": "to",
    "toi": "to",
    "tof": "to",
    "tob": "to",
    "tryi": "try",
    "tryf": "try",
    "len": "len",
    "push": "push",
    "pop": "pop",
    "clone": "clone",
    "isnull": "isnull",
    "cstr": "cstr",
    "alloc": "alloc",
    "free": "free",
    "readfile": "readfile",
    "writefile": "writefile",
    "fopen": "fopen",
}

_STD_NAMESPACES = ("str", "list", "rand", "time", "fs", "task")

MATH_MEMBERS = {
    "sqrt": 1,
    "abs": 1,
    "floor": 1,
    "ceil": 1,
    "round": 1,
    "min": 2,
    "max": 2,
    "sin": 1,
    "cos": 1,
    "tan": 1,
    "atan": 1,
    "atan2": 2,
    "pow": 2,
    "exp": 1,
    "log": 1,
}

STD_CONSTANTS = {
    "math.pi": T.F,
    "math.e": T.F,
}

_RESERVED_C = {
    "abs", "pow", "exit", "time", "printf", "puts", "gets", "scanf", "fgets",
    "strlen", "strcmp", "strcpy", "memcpy", "memset", "malloc", "calloc",
    "realloc", "rand", "srand", "system", "remove", "fopen", "fclose", "sleep",
    "sqrt", "fabs",
}

_ORDER_NAMES = {"i": T.I, "u": T.U, "f": T.F, "b": T.B, "c": T.C, "s": T.S}


class Var:
    def __init__(self, ty, mutable, const, line, decl=None):
        self.ty = ty
        self.mutable = mutable
        self.const = const
        self.line = line
        self.decl = decl


class Checker:
    def __init__(self, program, reporter, filename):
        self.program = program
        self.reporter = reporter
        self.filename = filename
        self.functions = {}        # name -> [FnDecl]
        self.generic_functions = {}  # name -> [FnDecl]
        self.generic_cache = {}    # key -> FnDecl
        self.globals = {}          # name -> Var
        self.namespaces = {}       # name -> NamespaceDecl
        self.ns_functions = {}     # "ns.fn" -> [FnDecl]
        self.ns_constants = {}     # "ns.name" -> Var
        self.structs = {}          # concrete struct name -> StructDecl
        self.struct_fields = {}    # struct name -> {field: Ty}
        self.generic_structs = {}  # template name -> StructDecl
        self.struct_keys = {}      # mangled generic key -> concrete C name
        self.scopes = []
        self.loops = []
        self.current_fn = None
        self.type_env = {}
        self.in_top_level = True
        self.struct_types = []
        self.tuple_types = []
        self.module_aliases = dict(getattr(program, "module_aliases", {}) or {})

    # -- driver ----------------------------------------------------------
    def run(self):
        self.collect_structs()
        self.collect_top_level()
        self.prepare_structs()
        for g in self.program.globals:
            self.check_global(g)
        for ns in self.program.namespaces:
            self.check_namespace_constants(ns)
        for ns in self.program.namespaces:
            for fn in ns.functions:
                if fn.extern:
                    continue
                self.check_fn(fn)
        for fn in list(self.program.functions):
            if not fn.extern and not fn.type_params:
                self.check_fn(fn)
        self.check_main()
        self.program.struct_types = self.struct_types
        self.program.tuple_types = self.tuple_types
        self.program.externs = [f for f in self.program.functions if f.extern]
        self.program.externs.extend(getattr(self.program, "btl_externs", []) or [])
        return self.program

    def collect_structs(self):
        for s in self.program.structs:
            if s.type_params:
                if s.name in self.generic_structs:
                    self.reporter.error("struct '%s' is already defined" % s.name,
                                        s.line, s.col)
                self.generic_structs[s.name] = s
            else:
                if s.name in self.structs:
                    self.reporter.error("struct '%s' is already defined" % s.name,
                                        s.line, s.col)
                self.structs[s.name] = s

    def prepare_structs(self):
        for name, s in list(self.structs.items()):
            self.resolve_struct(s)

    def resolve_struct(self, s):
        if getattr(s, "resolved", False):
            return T.struct_type(s.name)
        s.resolved = True
        s.c_name = getattr(s, "c_name", s.name) or s.name
        fields = {}
        old = self.type_env
        try:
            self.type_env = getattr(s, "generic_env", {})
            for f in s.fields:
                ft = self.resolve_type(f.ty, f.line, f.col)
                if f.name in fields:
                    self.reporter.error("field '%s' is already declared" % f.name,
                                        f.line, f.col)
                fields[f.name] = ft
                f.ty = ft
        finally:
            self.type_env = old
        self.struct_fields[s.name] = fields
        if s not in self.struct_types:
            self.struct_types.append(s)
        return T.struct_type(s.name)

    # -- namespaces ------------------------------------------------------
    def resolve_ns_alias(self, name):
        return self.module_aliases.get(name, name)

    def collect_top_level(self):
        for ns in self.program.namespaces:
            self.collect_namespace(ns)
        for fn in self.program.functions:
            if fn.extern:
                # Externs bypass the builtin/reserved-name checks; they are the
                # explicit escape hatch to C.
                self.functions.setdefault(fn.name, []).append(fn)
                continue
            if fn.name in BUILTINS:
                self.reporter.error("'%s' is a builtin and cannot be redefined" % fn.name,
                                    fn.line, fn.col)
                continue
            if fn.name in _RESERVED_C:
                self.reporter.error("'%s' is reserved (it collides with the C runtime)" % fn.name,
                                    fn.line, fn.col)
                continue
            if fn.type_params:
                self.generic_functions.setdefault(fn.name, []).append(fn)
                continue
            self.resolve_signature(fn)
            existing = self.functions.get(fn.name)
            if existing:
                if not self.signatures_differ(existing, fn):
                    self.reporter.error("'%s' is already defined with this signature"
                                        % fn.name, fn.line, fn.col)
                    continue
                existing.append(fn)
            else:
                self.functions[fn.name] = [fn]

    def collect_namespace(self, ns):
        if ns.name in ("math",) or ns.name in _STD_NAMESPACES:
            self.reporter.error("the standard namespace '%s' cannot be redefined" % ns.name,
                                ns.line, ns.col)
            return
        if ns.name in self.namespaces:
            self.reporter.error("namespace '%s' is already defined" % ns.name,
                                ns.line, ns.col)
            return
        self.namespaces[ns.name] = ns
        for fn in ns.functions:
            self.resolve_signature(fn)
            key = "%s.%s" % (ns.name, fn.name)
            existing = self.ns_functions.get(key)
            if existing:
                if not self.signatures_differ(existing, fn):
                    self.reporter.error("'%s' is already defined with this signature"
                                        % key, fn.line, fn.col)
                    continue
                existing.append(fn)
            else:
                self.ns_functions[key] = [fn]

    def resolve_signature(self, fn):
        old = self.type_env
        try:
            self.type_env = getattr(fn, "generic_env", {})
            for p in fn.params:
                p.ty = self.resolve_type(p.ty, p.line, p.col)
            if fn.rets:
                fn.rets = [self.resolve_type(t, fn.line, fn.col) for t in fn.rets]
                fn.ret = fn.rets[0] if len(fn.rets) == 1 else T.tuple_type(fn.rets)
            elif fn.ret is not None:
                fn.ret = self.resolve_type(fn.ret, fn.line, fn.col)
        finally:
            self.type_env = old

    @staticmethod
    def signatures_differ(existing, fn):
        sig = [(p.ty for p in fn.params), tuple(fn.rets)]
        for other in existing:
            if [(p.ty for p in other.params), tuple(other.rets)] == sig:
                return False
        return True

    def check_main(self):
        fns = self.functions.get("main")
        if not fns:
            self.reporter.error("no 'fn main()' — a program needs an entry point")
            return
        main = fns[0]
        if main.params or main.ret is None or main.ret != T.I:
            self.reporter.error("'main' must be declared 'fn main() -> i'",
                                main.line, main.col)
        self.program.main = main

    # -- globals ---------------------------------------------------------
    def check_global(self, g):
        if len(g.names) != 1:
            self.reporter.error("a global holds one name", g.line, g.col)
        name = g.names[0]
        if name in self.globals:
            self.reporter.error("'%s' is already declared at the top level" % name, g.line, g.col)
            return
        if len(g.values) > 1:
            self.reporter.error("a global holds one value", g.line, g.col)
        value = g.values[0] if g.values else None
        if value is not None:
            self.expr(value)
        else:
            if g.ty is None:
                self.reporter.error("'%s' has no type prefix and no value to infer from"
                                    % name, g.line, g.col)
                g.ty = T.I
        self.declare_global_type(g, name, value)

    def declare_global_type(self, g, name, value):
        ty = self.resolve_type(g.ty, g.line, g.col) if g.ty is not None else None
        if ty is None:
            if value is None:
                self.reporter.error("'%s' needs a type prefix" % name, g.line, g.col)
                ty = T.I
            else:
                ty = self.infer_type(value)
                self.infer_warning(g, name, value)
        elif value is not None:
            self.expr(value, ty)
            self.assignable(value, ty, "'%s'" % name)
        g.ty = ty
        if g.is_const and value is not None and not self.is_constant(value):
            self.reporter.error("a const global needs a constant value", g.line, g.col)
        self.globals[name] = Var(ty, mutable=not g.is_const, const=g.is_const, line=g.line)
        g.inferred_type = ty

    @staticmethod
    def is_constant(node):
        return isinstance(node, (IntLit, FloatLit, StrLit, CharLit, BoolLit))

    # -- namespace constants ---------------------------------------------
    def check_namespace_constants(self, ns):
        for g in ns.constants:
            if len(g.names) != 1:
                self.reporter.error("a namespace constant holds one name", g.line, g.col)
                continue
            name = g.names[0]
            key = "%s.%s" % (ns.name, name)
            if key in self.ns_constants:
                self.reporter.error("'%s' is already declared" % key, g.line, g.col)
                continue
            if len(g.values) != 1:
                self.reporter.error("a namespace constant needs one value", g.line, g.col)
                continue
            value = g.values[0]
            self.expr(value)
            if g.ty is None:
                g.ty = self.infer_type(value)
            else:
                g.ty = self.resolve_type(g.ty, g.line, g.col)
                self.assignable(value, g.ty, "'%s'" % key)
            if not self.is_constant(value):
                self.reporter.error("a namespace constant needs a constant value",
                                    g.line, g.col)
                continue
            self.ns_constants[key] = Var(g.ty, mutable=False, const=True,
                                         line=g.line, decl=g)
            g.inferred_type = g.ty

    # -- functions -------------------------------------------------------
    def check_fn(self, fn):
        if getattr(fn, "check", False):
            return
        fn.check = True
        old_env = self.type_env
        old_fn = self.current_fn
        self.type_env = getattr(fn, "generic_env", {})
        self.current_fn = fn
        fn.local_vars = []
        self.scopes.append({})
        for p in fn.params:
            p.ty = self.resolve_type(p.ty, p.line, p.col)
            if p.name in self.scopes[-1]:
                self.reporter.error("duplicate parameter '%s'" % p.name, p.line, p.col)
            self.scopes[-1][p.name] = Var(p.ty, True, False, p.line)
            fn.local_vars.append((p.name, p.ty))
        if fn.rets:
            fn.rets = [self.resolve_type(t, fn.line, fn.col) for t in fn.rets]
            fn.ret = fn.rets[0] if len(fn.rets) == 1 else T.tuple_type(fn.rets)
        elif fn.ret is not None:
            fn.ret = self.resolve_type(fn.ret, fn.line, fn.col)
        self.stmt(fn.body)
        if getattr(fn, "det_return", False) and fn.ret is None:
            fn.ret = T.VOID
        self.scopes.pop()
        if fn.ret is not None and not ends_with_return(fn.body):
            self.codegen_pad = True
        self.current_fn = old_fn
        self.type_env = old_env

    # -- scope helpers ---------------------------------------------------
    def push(self):
        self.scopes.append({})

    def pop(self):
        self.scopes.pop()

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return self.globals.get(name)

    def declare(self, name, var, line, col):
        if not self.scopes:
            self.reporter.error("internal: declaration outside any scope", line, col)
            return
        if name in self.scopes[-1]:
            self.reporter.error("'%s' is already declared in this block" % name, line, col)
            return
        self.scopes[-1][name] = var

    # -- type resolution -------------------------------------------------
    def resolve_type(self, ty, line=0, col=0):
        if ty is None:
            return None
        if ty.kind == "named":
            name = ty.name_
            if name in self.type_env:
                return self.type_env[name]
            if name == "File":
                return T.FILE
            if name == "Task":
                return T.TASK
            if name in self.structs:
                return T.struct_type(name)
            if name in self.generic_structs:
                self.reporter.error("generic struct '%s' needs type arguments" % name, line, col)
                return T.I
            self.reporter.error("unknown type '%s'" % name, line, col)
            return T.I
        if ty.kind == "struct":
            name = ty.name_
            if name in self.generic_structs:
                args = [self.resolve_type(a, line, col) for a in ty.args]
                return self.instantiate_struct(self.generic_structs[name], args, line, col)
            if name in self.structs:
                if ty.args:
                    self.reporter.error("struct '%s' does not take type arguments" % name,
                                        line, col)
                return T.struct_type(name)
            if not ty.args and name in ("File", "Task"):
                return T.FILE if name == "File" else T.TASK
            self.reporter.error("unknown type '%s'" % name, line, col)
            return T.I
        if ty.kind == "pointer":
            return T.pointer_to(self.resolve_type(ty.elem, line, col))
        if ty.kind == "array":
            return T.array_of(self.resolve_type(ty.elem, line, col), ty.size)
        if ty.kind == "list":
            return T.list_of(self.resolve_type(ty.elem, line, col))
        if ty.kind == "tuple":
            return T.tuple_type([self.resolve_type(x, line, col) for x in ty.elems])
        return ty

    def instantiate_struct(self, template, args, line=0, col=0):
        key = "%s<%s>" % (template.name, ",".join(a.mangle for a in args))
        cname = "%s__%s" % (template.name, "__".join(a.mangle for a in args))
        if key in self.struct_keys:
            return T.struct_type(self.struct_keys[key])
        env = {p.name: a for p, a in zip(template.type_params, args)}
        for p, a in zip(template.type_params, args):
            if not T.constraint_ok(a, p.constraint):
                self.reporter.error("type '%s' does not satisfy %s: %s"
                                    % (a.name, p.name, p.constraint), line, col)
        clone = copy.deepcopy(template)
        clone.name = cname
        clone.c_name = cname
        clone.type_params = []
        clone.generic_env = env
        clone.parent_generic = template.name
        self.struct_keys[key] = cname
        self.structs[cname] = clone
        self.resolve_struct(clone)
        return T.struct_type(cname)

    # -- statements ------------------------------------------------------
    def stmt(self, node):
        method = getattr(self, "stmt_" + type(node).__name__, None)
        if method is None:
            raise CompileError("internal: unhandled statement %s" % type(node).__name__,
                               node.line, node.col)
        method(node)

    def stmt_Block(self, node):
        self.push()
        for s in node.stmts:
            self.stmt(s)
        self.pop()

    def stmt_VarDecl(self, node):
        # A tuple-returning call may initialize several names at once.
        if len(node.values) == 1 and len(node.names) > 1:
            value = node.values[0]
            self.expr(value)
            if value.ty is not None and value.ty.kind == "tuple":
                if len(value.ty.elems) != len(node.names):
                    self.reporter.error("'%s' returns %d values, but %d names are declared"
                                        % (self.call_name(value), len(value.ty.elems),
                                           len(node.names)), node.line, node.col)
                for i, name in enumerate(node.names):
                    ty = None
                    if i < len(node.tys) and node.tys[i] is not None:
                        ty = self.resolve_type(node.tys[i], node.line, node.col)
                    if ty is None and i < len(value.ty.elems):
                        ty = value.ty.elems[i]
                    if ty is None:
                        ty = T.I
                    node.tys[i] = ty
                    self.declare(name, Var(ty, mutable=not node.is_const,
                                           const=node.is_const, line=node.line, decl=node),
                                 node.line, node.col)
                node.unpack_from = value
                node.ty = node.tys[0]
                return
        tys = []
        for i, name in enumerate(node.names):
            ty = None
            if i < len(node.tys) and node.tys[i] is not None:
                ty = self.resolve_type(node.tys[i], node.line, node.col)
            if ty is None and node.values:
                if len(node.values) == len(node.names):
                    self.expr(node.values[i])
                    ty = self.infer_type(node.values[i])
                    self.infer_warning(node, name, node.values[i])
                elif len(node.values) == 1:
                    self.expr(node.values[0])
                    ty = self.infer_type(node.values[0])
                else:
                    self.reporter.error("declaration needs one value per name",
                                        node.line, node.col)
                    ty = T.I
            if ty is None:
                self.reporter.error(
                    "'%s' needs a type prefix — there is no value to infer from" % name,
                    node.line, node.col)
                ty = T.I
            tys.append(ty)
        node.tys = tys
        node.ty = tys[0] if tys else T.I
        for i, name in enumerate(node.names):
            value = node.values[i] if i < len(node.values) else None
            if value is not None and len(node.values) == len(node.names):
                self.expr(value, tys[i])
                self.assignable(value, tys[i], "'%s'" % name)
            self.declare(name, Var(tys[i], mutable=not node.is_const,
                                   const=node.is_const, line=node.line, decl=node),
                         node.line, node.col)

    @staticmethod
    def call_name(node):
        if isinstance(node, Call):
            return node.name
        return "call"

    def stmt_Assign(self, node):
        # tuple unpacking
        if len(node.values) == 1 and len(node.targets) > 1:
            value = node.values[0]
            self.expr(value)
            if value.ty is not None and value.ty.kind == "tuple":
                if len(value.ty.elems) != len(node.targets):
                    self.reporter.error("assignment needs the same number of names and values",
                                        node.line, node.col)
                for tgt, ty in zip(node.targets, value.ty.elems):
                    self.check_lvalue(tgt, ty)
                node.unpack_from = value
                return
        targets = []
        for tgt in node.targets:
            if isinstance(tgt, Name) and "." in tgt.name:
                self.reporter.error("can only assign to a variable", tgt.line, tgt.col)
                targets.append(None)
                continue
            var = self.check_lvalue(tgt, None)
            targets.append(var)
        for i, v in enumerate(node.values):
            ty = targets[i].ty if i < len(targets) and targets[i] else None
            self.expr(v, ty)
            if ty is not None:
                self.assignable(v, ty, "'%s'" % self.describe_lvalue(node.targets[i]))
        for i, var in enumerate(targets):
            if var is None or i >= len(node.values):
                continue
            self.assignable(node.values[i], var.ty, "'%s'" % self.describe_lvalue(node.targets[i]))

    def describe_lvalue(self, node):
        if isinstance(node, Name):
            return node.name
        if isinstance(node, Member):
            return node.name
        if isinstance(node, Index):
            return "element"
        if isinstance(node, Deref):
            return "pointee"
        return "value"

    def check_lvalue(self, tgt, expected):
        if isinstance(tgt, Name):
            var = self.lookup(tgt.name)
            if var is None:
                self.reporter.error("'%s' is not declared" % tgt.name, tgt.line, tgt.col)
                return None
            if not var.mutable:
                self.reporter.error("'%s' is const and cannot be assigned" % tgt.name,
                                    tgt.line, tgt.col)
            tgt.ty = var.ty
            tgt.var = var
            return var
        if isinstance(tgt, Member):
            self.expr_Member(tgt)
            return Var(tgt.ty, mutable=True, const=False, line=tgt.line)
        if isinstance(tgt, Index):
            self.expr_Index(tgt)
            return Var(tgt.ty, mutable=True, const=False, line=tgt.line)
        if isinstance(tgt, Deref):
            self.expr_Deref(tgt)
            return Var(tgt.ty, mutable=True, const=False, line=tgt.line)
        self.reporter.error("can only assign to a variable, field, or element",
                            tgt.line, tgt.col)
        return None

    def stmt_ExprStmt(self, node):
        self.expr(node.expr)

    def stmt_If(self, node):
        for cond, body in node.branches:
            self.expr(cond, T.B)
            self.condition(cond, "if")
            self.stmt(body)
        if node.otherwise is not None:
            self.stmt(node.otherwise)

    def stmt_While(self, node):
        self.expr(node.cond, T.B)
        self.condition(node.cond, "while")
        self.loops.append({"label": node.label, "line": node.line, "kind": "while"})
        self.push()
        self.stmt(node.body)
        self.pop()
        self.loops.pop()

    def stmt_ForRange(self, node):
        self.expr(node.start)
        self.expr(node.end)
        if node.step is not None:
            self.expr(node.step)
        start_ty = node.start.ty
        if not (start_ty.is_int or start_ty.kind == "char"):
            self.reporter.error("a range needs an integer start, found %s"
                                % start_ty.gloss, node.start.line, node.start.col)
            start_ty = T.I
        if start_ty.kind == "char":
            start_ty = T.U8
        node.var_ty = start_ty
        for other, what in ((node.end, "end"), (node.step, "step")):
            if other is None:
                continue
            if other.ty.kind == "char" or other.ty.is_int:
                self.coerce(other, start_ty)
            else:
                self.reporter.error("the range %s must be an integer, found %s"
                                    % (what, other.ty.gloss), other.line, other.col)
        self.loops.append({"label": node.label, "line": node.line, "kind": "for"})
        self.push()
        self.declare(node.var, Var(start_ty, mutable=False, const=True, line=node.line),
                     node.line, node.col)
        self.stmt(node.body)
        self.pop()
        self.loops.pop()

    def stmt_ForEach(self, node):
        self.expr(node.iterable)
        iter_ty = node.iterable.ty
        elem = iter_ty.element_type() if iter_ty is not None else None
        if elem is None:
            self.reporter.error("cannot iterate a %s" % (iter_ty.gloss if iter_ty else "value"),
                                node.iterable.line, node.iterable.col)
            elem = T.I
        node.value_ty = elem
        self.loops.append({"label": node.label, "line": node.line, "kind": "for"})
        self.push()
        if node.index_var:
            self.declare(node.index_var, Var(T.I, mutable=False, const=True, line=node.line),
                         node.line, node.col)
        self.declare(node.value_var, Var(elem, mutable=False, const=True, line=node.line),
                     node.line, node.col)
        self.stmt(node.body)
        self.pop()
        self.loops.pop()

    def stmt_Loop(self, node):
        self.loops.append({"label": node.label, "line": node.line, "kind": "loop"})
        self.push()
        self.stmt(node.body)
        self.pop()
        self.loops.pop()

    def stmt_Break(self, node):
        self._check_jump(node, node.label, "break")

    def stmt_Continue(self, node):
        self._check_jump(node, node.label, "continue")

    def _check_jump(self, node, label, kind):
        if not self.loops:
            self.reporter.error("'%s' outside a loop" % kind, node.line, node.col)
            return
        if label is None:
            return
        index = None
        for i in range(len(self.loops) - 1, -1, -1):
            if self.loops[i]["label"] == label:
                index = i
                break
        if index is None:
            self.reporter.error("no loop labelled '%s'" % label, node.line, node.col)
            return
        loop = self.loops[index]
        node.loop_id = id(loop)
        node.target = loop

    def stmt_Return(self, node):
        if self.current_fn is None:
            self.reporter.error("'return' outside a function", node.line, node.col)
            return
        fn = self.current_fn
        rets = fn.rets or ([] if fn.ret is None else [fn.ret])
        if not node.values:
            if rets:
                expected = rets[0] if len(rets) == 1 else "values"
                self.reporter.error("'%s' must return %s" % (fn.name, expected),
                                    node.line, node.col)
            return
        for value in node.values:
            self.expr(value)
        if not rets and getattr(fn, "det_return", False):
            if len(node.values) == 1:
                fn.ret = node.values[0].ty
                fn.rets = [fn.ret]
                fn.det_return = False
                return
        if len(node.values) != len(rets):
            if len(rets) == 1 and len(node.values) == 1:
                self.assignable(node.values[0], rets[0], "'%s'" % fn.name)
                return
            if not rets and len(node.values) == 1:
                self.reporter.error("'%s' returns nothing, but a value is given"
                                    % fn.name, node.line, node.col)
                return
            self.reporter.error("'%s' returns %d value%s, but %d %s given"
                                % (fn.name, len(rets), "" if len(rets) == 1 else "s",
                                   len(node.values), "is" if len(node.values) == 1 else "are"),
                                node.line, node.col)
            return
        for value, ret in zip(node.values, rets):
            self.assignable(value, ret, "'%s'" % fn.name)

    def stmt_Match(self, node):
        self.expr(node.subject)
        subject_ty = node.subject.ty
        has_else = False
        for arm in node.arms:
            if arm.patterns is None:
                has_else = True
            else:
                for pat in arm.patterns:
                    self.check_pattern(pat, subject_ty)
            self.stmt(arm.body)
        if not has_else and not (subject_ty == T.B):
            self.reporter.error("'match' needs an else arm", node.line, node.col)

    def check_pattern(self, pat, subject_ty):
        if isinstance(pat, RangePattern):
            self.expr(pat.lo, subject_ty)
            self.expr(pat.hi, subject_ty)
            if not (subject_ty.is_numeric or subject_ty.kind in ("char", "str")):
                self.reporter.error("a range pattern needs an ordered type",
                                    pat.line, pat.col)
            return
        self.expr(pat, subject_ty)
        if pat.ty != subject_ty:
            self.assignable(pat, subject_ty, "pattern")

    # -- type helpers ----------------------------------------------------
    def condition(self, node, context):
        ty = node.ty
        if ty == T.B:
            return
        hint = "try adding '!= 0'" if (ty.is_numeric or ty.kind == "char") else None
        self.reporter.error("'%s' condition must be b, found %s" % (context, ty.gloss),
                            node.line, node.col, node.span, hint=hint)

    def infer_type(self, node):
        ty = node.ty
        if ty is None:
            return T.I
        return ty

    def coerce(self, node, target):
        src = node.ty
        if src == target or target is None:
            return
        node.coerce_to = target

    def assignable(self, node, target, what):
        try:
            self._assignable(node, target, what)
        except CompileError as e:
            self.reporter.error(e)

    def _assignable(self, node, target, what):
        src = node.ty
        if src == target:
            return
        if target is None:
            return
        # Literals adapt to their context (section 5).
        if isinstance(node, IntLit) or (isinstance(node, Unary) and node.op == "-"
                                        and isinstance(node.operand, IntLit)):
            value = node.value if isinstance(node, IntLit) else -node.operand.value
            if target.is_int:
                if not T.fits_integer(value, target):
                    lo, hi = (T.signed_range(target.bits) if target.kind == "int"
                              else T.unsigned_range(target.bits))
                    raise CompileError("%s does not fit in %s (its range is %d to %d)"
                                       % (fmt_int(value), target.name, lo, hi),
                                       node.line, node.col, node.span)
                node.coerce_to = target
                node.ty = target
                return
            if target.is_float:
                node.coerce_to = target
                node.ty = target
                return
        if isinstance(node, FloatLit):
            if target.is_float:
                node.coerce_to = target
                node.ty = target
                return
            if target.is_int:
                raise CompileError("%s needs 'as %s' to become an integer" % (what, target.name),
                                   node.line, node.col, node.span)
        if T.can_auto_convert(src, target):
            node.coerce_to = target
            return
        if src.is_numeric and target.is_numeric and src.kind != target.kind and \
                src.is_int and target.is_int and src.is_signed_int != target.is_signed_int:
            raise CompileError("%s is %s but must be %s — signed and unsigned cannot be "
                               "mixed without 'as'" % (what, src.name, target.name),
                               node.line, node.col, node.span)
        if src.is_numeric and target.is_numeric:
            raise CompileError("cannot assign %s to %s; write '%s' to convert"
                               % (src.name, target.name, "as %s" % target.name),
                               node.line, node.col, node.span)
        if src.kind == "array" and target.kind == "array" and src.size == target.size:
            self.assignable_elements(node, src, target, what)
            return
        raise CompileError("%s is %s but must be %s" % (what, src.name, target.name),
                           node.line, node.col, node.span)

    def assignable_elements(self, node, src, target, what):
        # Empty brace literals and array literals are checked contextually.
        if isinstance(node, BraceLit):
            return
        raise CompileError("%s is %s but must be %s" % (what, src.name, target.name),
                           node.line, node.col, node.span)

    def infer_warning(self, decl, name, value):
        ty = self.infer_type(value)
        self.reporter.warn(
            "no type prefix on '%s', inferred '%s' (%s)" % (name, ty.name, ty.gloss),
            decl.line, decl.col, span=None, hint=None)

    # -- expressions -----------------------------------------------------
    def expr(self, node, expected=None):
        method = getattr(self, "expr_" + type(node).__name__, None)
        if method is None:
            raise CompileError("internal: unhandled expression %s" % type(node).__name__,
                               node.line, node.col)
        if expected is not None:
            expected = self.resolve_type(expected, node.line, node.col)
        method(node, expected)
        return node.ty

    def expr_IntLit(self, node, expected=None):
        node.ty = T.I

    def expr_FloatLit(self, node, expected=None):
        node.ty = T.F

    def expr_StrLit(self, node, expected=None):
        node.ty = T.S

    def expr_CharLit(self, node, expected=None):
        node.ty = T.C

    def expr_BoolLit(self, node, expected=None):
        node.ty = T.B

    def expr_Name(self, node, expected=None):
        if "." in node.name:
            var = self.ns_constants.get(node.name)
            if var is not None:
                node.ty = var.ty
                node.var = var
                namespace, _, member = node.name.partition(".")
                node.c_name = "%s_%s" % (namespace, member)
                return
            if node.name in STD_CONSTANTS:
                node.ty = STD_CONSTANTS[node.name]
                node.std_constant = node.name
                return
            namespace, _, member = node.name.partition(".")
            if namespace in self.namespaces or self.resolve_ns_alias(namespace) in self.namespaces:
                raise CompileError("'%s' is not a constant in namespace '%s'"
                                   % (node.name, namespace), node.line, node.col, node.span)
            if namespace == "math":
                raise CompileError("'%s' is not a math constant; math has pi and e"
                                   % node.name, node.line, node.col, node.span)
            raise CompileError("'%s' is not a standard library name" % node.name,
                               node.line, node.col, node.span)
        var = self.lookup(node.name)
        if var is None:
            raise CompileError("'%s' is not declared" % node.name, node.line, node.col, node.span)
        node.ty = var.ty
        node.var = var

    def expr_Unary(self, node, expected=None):
        self.expr(node.operand)
        src = node.operand.ty
        if node.op == "not":
            if src != T.B:
                raise CompileError("'not' needs a b, found %s" % src.gloss,
                                   node.line, node.col, node.span)
            node.ty = T.B
            return
        if node.op == "~":
            if not (src.is_int or src.kind == "char"):
                raise CompileError("'~' needs an integer, found %s" % src.gloss,
                                   node.line, node.col, node.span)
            node.ty = T.I if src.kind == "char" else src
            return
        if not src.is_numeric:
            raise CompileError("'-' needs a number, found %s" % src.gloss,
                               node.line, node.col, node.span)
        node.ty = src

    def expr_AddrOf(self, node, expected=None):
        self.expr(node.operand)
        if not self.is_lvalue(node.operand):
            raise CompileError("'&' needs a variable, field, or element",
                               node.line, node.col, node.span)
        node.ty = T.pointer_to(node.operand.ty)

    def expr_Deref(self, node, expected=None):
        self.expr(node.operand)
        ty = node.operand.ty
        if ty is None or ty.kind != "pointer":
            raise CompileError("'*' needs a pointer, found %s" % (ty.gloss if ty else "value"),
                               node.line, node.col, node.span)
        node.ty = ty.elem
        node.lvalue = True

    @staticmethod
    def is_lvalue(node):
        return isinstance(node, (Name, Member, Index, Deref))

    def expr_Cast(self, node, expected=None):
        self.expr(node.operand)
        dst = self.resolve_type(node.target, node.line, node.col)
        src = node.operand.ty
        node.target = dst
        if src == dst:
            node.ty = dst
            return
        if src == T.B or dst == T.B or src == T.S or dst == T.S:
            raise CompileError("'as' cannot convert between %s and %s — b and s never convert"
                               % (src.gloss, dst.gloss), node.line, node.col, node.span)
        if src.kind == "pointer" or dst.kind == "pointer":
            node.ty = dst
            return
        node.ty = dst

    def expr_BraceLit(self, node, expected=None):
        if expected is not None and expected.kind == "struct":
            self.check_struct_literal(node, expected)
            return
        if expected is not None and expected.kind == "array":
            self.check_array_literal(node, expected)
            return
        if expected is not None and expected.kind == "list":
            node.kind = "list"
            node.ty = expected
            for _, value in node.entries:
                self.expr(value, expected.elem)
                self.assignable(value, expected.elem, "list element")
            return
        if expected is not None and expected.kind == "tuple":
            node.kind = "tuple"
            node.ty = expected
            return
        if expected is not None:
            raise CompileError("a brace literal cannot initialize %s" % expected.name,
                               node.line, node.col, node.span)
        # Without context, a positional brace literal is a growable list.
        if not node.entries:
            node.kind = "list"
            node.ty = T.list_of(T.I)
            return
        if all(name is not None for name, _ in node.entries):
            raise CompileError("a struct literal needs a struct type", node.line, node.col)
        for _, value in node.entries:
            self.expr(value)
        elem = self.infer_type(node.entries[0][1])
        for _, value in node.entries[1:]:
            elem = T.unify(elem, value.ty) or elem
        node.kind = "list"
        node.ty = T.list_of(elem)
        for _, value in node.entries:
            self.assignable(value, elem, "list element")

    def check_struct_literal(self, node, expected):
        fields = self.struct_fields.get(expected.name_, {})
        node.kind = "struct"
        node.ty = expected
        seen = set()
        resolved_entries = []
        for i, (name, value) in enumerate(node.entries):
            if name is None:
                names = list(fields)
                if i >= len(names):
                    raise CompileError("too many fields for %s" % expected.name_,
                                       node.line, node.col, node.span)
                name = names[i]
            if name not in fields:
                raise CompileError("'%s' has no field '%s'" % (expected.name_, name),
                                   value.line, value.col)
            if name in seen:
                raise CompileError("field '%s' is set more than once" % name,
                                   value.line, value.col)
            seen.add(name)
            self.expr(value, fields[name])
            self.assignable(value, fields[name], "field '%s'" % name)
            resolved_entries.append((name, value))
        node.resolved_entries = resolved_entries

    def check_array_literal(self, node, expected):
        node.kind = "array"
        node.ty = expected
        if len(node.entries) > expected.size:
            raise CompileError("too many elements for %s (expected %d)"
                               % (expected.name, expected.size),
                               node.line, node.col, node.span)
        for _, value in node.entries:
            self.expr(value, expected.elem)
            self.assignable(value, expected.elem, "array element")

    def expr_Member(self, node, expected=None):
        # A namespace constant such as math.pi or calc.base.
        if isinstance(node.obj, Name):
            ns = self.resolve_ns_alias(node.obj.name)
            if ns in self.namespaces or ns == "math":
                key = "%s.%s" % (ns, node.name)
                if key in self.ns_constants:
                    node.ty = self.ns_constants[key].ty
                    node.ns_constant = key
                    node.c_name = "%s_%s" % (ns, node.name)
                    return
                if key in STD_CONSTANTS:
                    node.ty = STD_CONSTANTS[key]
                    node.std_constant = key
                    return
                if ns == "math":
                    raise CompileError("'%s' is not a math constant; math has pi and e" % key,
                                       node.line, node.col, node.span)
                raise CompileError("'%s' is not a constant in namespace '%s'"
                                   % (node.name, ns), node.line, node.col, node.span)
        self.expr(node.obj)
        ty = node.obj.ty
        auto = False
        if ty.kind == "pointer" and ty.elem.kind == "struct":
            ty = ty.elem
            auto = True
        if ty.kind != "struct":
            if ty.kind == "file" or ty.kind == "task":
                raise CompileError("'%s' is a method; call it with '%s.%s(...)'"
                                   % (node.name, "value", node.name),
                                   node.line, node.col, node.span)
            raise CompileError("'%s' has no field '%s'" % (ty.gloss, node.name),
                               node.line, node.col, node.span)
        fields = self.struct_fields.get(ty.name_, {})
        if node.name not in fields:
            raise CompileError("struct '%s' has no field '%s'" % (ty.name_, node.name),
                               node.line, node.col, node.span)
        node.ty = fields[node.name]
        node.struct_ty = ty
        node.field = node.name
        node.auto_deref = auto
        node.lvalue = True

    def expr_MethodCall(self, node, expected=None):
        # Namespace call (`calc.add(...)`) or a method on a value (`f.write(...)`).
        for arg in node.args:
            self.expr(arg)
        if isinstance(node.obj, Name):
            ns = self.resolve_ns_alias(node.obj.name)
            if ns in self.namespaces or ns in _STD_NAMESPACES or ns == "math":
                call = Call("%s.%s" % (ns, node.name), node.args, node.line, node.col,
                            node.span)
                node.ty = self.check_qualified_call(call)
                call.ty = node.ty
                node.namespace_call = call
                return
            # list.clone() / list.push(x) style, where list is a variable.
            var = self.lookup(node.obj.name)
            if var is not None and var.ty.kind == "list" and node.name in ("clone", "push", "pop", "len"):
                self.expr(node.obj)
                call = Call(node.name, [node.obj] + node.args, node.line, node.col, node.span)
                node.ty = self.check_builtin(call)
                node.method_builtin = call
                return
        self.expr(node.obj)
        ty = node.obj.ty
        if ty.kind == "file":
            node.ty = self.check_file_method(node, ty)
            return
        if ty.kind == "list" and node.name == "clone":
            self.expr(node.args[0]) if node.args else None
            call = Call("clone", [node.obj], node.line, node.col, node.span)
            node.ty = self.check_builtin(call)
            node.method_builtin = call
            return
        raise CompileError("'%s' has no method '%s'" % (ty.gloss, node.name),
                           node.line, node.col, node.span)

    def expr_Index(self, node, expected=None):
        self.expr(node.obj)
        self.expr(node.index, T.I)
        ty = node.obj.ty
        if ty.kind not in ("list", "array", "pointer", "str"):
            raise CompileError("cannot index a %s" % ty.gloss, node.line, node.col, node.span)
        if not (node.index.ty.is_int or node.index.ty.kind == "char"):
            raise CompileError("an index must be an integer, found %s" % node.index.ty.gloss,
                               node.index.line, node.index.col)
        node.ty = ty.element_type()
        node.lvalue = True

    def expr_Slice(self, node, expected=None):
        self.expr(node.obj)
        for part in (node.start, node.end):
            if part is not None:
                self.expr(part, T.I)
        ty = node.obj.ty
        if ty.kind not in ("list", "array", "str"):
            raise CompileError("cannot slice a %s" % ty.gloss, node.line, node.col, node.span)
        if ty.kind == "str":
            node.ty = T.S
        else:
            node.ty = T.list_of(ty.element_type())

    def expr_Binary(self, node, expected=None):
        self.expr(node.left)
        self.expr(node.right)
        op = node.op

        if op in ("and", "or"):
            for side in (node.left, node.right):
                if side.ty != T.B:
                    raise CompileError("'%s' needs b on both sides, found %s"
                                       % (op, side.ty.gloss), side.line, side.col, side.span)
            node.ty = T.B
            return

        if op in ("==", "!=", "<", "<=", ">", ">="):
            node.ty = T.B
            self._check_comparison(node)
            return

        if op == "@":
            node.ty = self._matrix_multiply(node)
            return

        if op in ("&", "|", "^", "<<", ">>"):
            node.ty = self._bitwise(node)
            return

        if op == "**":
            if node.left.ty.is_int and node.right.ty.is_int:
                node.ty = self._promote_arith(node)
                return
            if node.left.ty.is_float and node.right.ty.is_float:
                node.ty = self._promote_arith(node)
                return
            raise CompileError("'**' needs two numbers of the same kind, found %s and %s"
                               % (node.left.ty.gloss, node.right.ty.gloss),
                               node.line, node.col, node.span)

        # Matrix and array arithmetic.
        if self.is_array_like(node.left.ty) or self.is_array_like(node.right.ty):
            node.ty = self._array_arith(node)
            return

        # Pointer arithmetic.
        if node.left.ty.kind == "pointer" or node.right.ty.kind == "pointer":
            node.ty = self._pointer_arith(node)
            return

        if op == "+" and node.left.ty == T.S and node.right.ty == T.S:
            node.ty = T.S
            return
        if node.left.ty == T.S or node.right.ty == T.S:
            raise CompileError("'%s' cannot be used with s; only '+' joins strings and "
                               "comparisons compare them" % op, node.line, node.col, node.span)
        if op == "%" and (node.left.ty.is_float or node.right.ty.is_float):
            raise CompileError("'%%' needs two integers, found %s and %s"
                               % (node.left.ty.gloss, node.right.ty.gloss),
                               node.line, node.col, node.span)
        node.ty = self._promote_arith(node)

    @staticmethod
    def is_array_like(ty):
        return ty.kind in ("array", "list")

    def _matrix_multiply(self, node):
        left, right = node.left.ty, node.right.ty
        if not (left.kind == "array" and right.kind == "array" and
                left.elem.kind == "array" and right.elem.kind == "array"):
            raise CompileError("'@' needs two 2-D arrays, found %s and %s"
                               % (left.name, right.name), node.line, node.col, node.span)
        rows, inner = left.size, left.elem.size
        if right.size != inner:
            raise CompileError("matrix dimensions do not line up: %s @ %s"
                               % (left.name, right.name), node.line, node.col, node.span)
        elem = T.promote(left.elem.elem, right.elem.elem)
        if elem is None:
            elem = left.elem.elem if left.elem.elem == right.elem.elem else T.F
        node.matrix_ty = T.array_of(T.array_of(elem, right.elem.size), rows)
        return node.matrix_ty

    def _array_arith(self, node):
        left, right = node.left.ty, node.right.ty
        op = node.op
        if left.kind in ("array", "list") and right.is_numeric and op in ("*", "/"):
            elem = left.element_type()
            if elem.kind == "array":
                node.array_scalar = right
                return left
            if not elem.is_numeric:
                raise CompileError("'%s' needs a numeric array" % op,
                                   node.line, node.col, node.span)
            return left
        if left.is_numeric and right.kind in ("array", "list") and op == "*":
            node.array_scalar = left
            return right
        if left.kind in ("array", "list") and right.kind in ("array", "list") and op in ("+", "-"):
            if left.kind != right.kind or left.element_type() != right.element_type():
                raise CompileError("array arithmetic needs matching element types, found %s and %s"
                                   % (left.name, right.name), node.line, node.col, node.span)
            if left.kind == "array" and left.size != right.size:
                raise CompileError("array arithmetic needs matching sizes, found %s and %s"
                                   % (left.name, right.name), node.line, node.col, node.span)
            elem = left.element_type()
            if elem.kind == "array" or elem.is_numeric:
                return left
            raise CompileError("array arithmetic needs numeric elements", node.line, node.col)
        raise CompileError("'%s' cannot combine %s and %s" % (op, left.name, right.name),
                           node.line, node.col, node.span)

    def _pointer_arith(self, node):
        left, right = node.left.ty, node.right.ty
        op = node.op
        if op not in ("+", "-"):
            raise CompileError("'%s' cannot be used with pointers" % op,
                               node.line, node.col, node.span)
        if left.kind == "pointer" and right.kind == "pointer":
            if op != "-" or left.elem != right.elem:
                raise CompileError("pointer arithmetic needs matching pointer types",
                                   node.line, node.col, node.span)
            return T.I
        if left.kind == "pointer" and right.is_int:
            return left
        if op == "+" and left.is_int and right.kind == "pointer":
            return right
        raise CompileError("'%s' needs a pointer and an integer" % op,
                           node.line, node.col, node.span)

    def _promote_arith(self, node):
        left, right = node.left.ty, node.right.ty
        result = T.promote(left, right)
        if result is None:
            result = self._unify_with_literal(node.left, node.right)
            if result is None:
                raise CompileError("'%s' cannot mix %s and %s" % (node.op, left.name, right.name),
                                   node.line, node.col, node.span)
        self.coerce(node.left, result)
        self.coerce(node.right, result)
        return result

    def _unify_with_literal(self, left, right):
        for lit, other in ((left, right), (right, left)):
            if isinstance(lit, IntLit) and other.ty.is_int:
                if T.fits_integer(lit.value, other.ty):
                    lit.coerce_to = other.ty
                    lit.ty = other.ty
                    return other.ty
        for lit, other in ((left, right), (right, left)):
            if isinstance(lit, IntLit) and other.ty.is_float:
                lit.coerce_to = other.ty
                lit.ty = other.ty
                return other.ty
        return None

    def _bitwise(self, node):
        pairs = ((node.left, "left"), (node.right, "right"))
        for side, which in pairs:
            if not (side.ty.is_int or side.ty.kind == "char"):
                raise CompileError("the %s side of '%s' must be an integer, found %s"
                                   % (which, node.op, side.ty.gloss),
                                   side.line, side.col, side.span)
            if side.ty.kind == "char":
                self.coerce(side, T.I)
        if node.op in ("<<", ">>"):
            return node.left.ty
        left, right = node.left.ty, node.right.ty
        result = T.promote(left if left.is_int else T.I, right if right.is_int else T.I)
        if result is None:
            raise CompileError("'%s' cannot mix %s and %s" % (node.op, left.name, right.name),
                               node.line, node.col, node.span)
        self.coerce(node.left, result)
        self.coerce(node.right, result)
        return result

    def _check_comparison(self, node):
        left, right = node.left.ty, node.right.ty
        if left.kind == "pointer" or right.kind == "pointer":
            if left != right or node.op not in ("==", "!="):
                raise CompileError("pointers compare with == and != only",
                                   node.line, node.col, node.span)
            return
        if left == T.S or right == T.S:
            if left == T.S and right == T.S:
                return
            raise CompileError("comparing a string to a %s is a type error"
                               % (right.gloss if left == T.S else left.gloss),
                               node.line, node.col, node.span)
        if left == T.B or right == T.B:
            if left == T.B and right == T.B and node.op in ("==", "!="):
                return
            raise CompileError("'%s' cannot compare %s with %s" % (node.op, left.name, right.name),
                               node.line, node.col, node.span)
        if left.is_numeric and right.is_numeric:
            result = T.promote(left, right)
            if result is None:
                result = self._unify_with_literal(node.left, node.right)
            if result is None:
                raise CompileError("'%s' cannot mix %s and %s — signed and unsigned cannot be "
                                   "mixed without 'as'" % (node.op, left.name, right.name),
                                   node.line, node.col, node.span)
            self.coerce(node.left, result)
            self.coerce(node.right, result)
            return
        if left.kind == "char" and right.kind == "char":
            return
        raise CompileError("'%s' cannot compare %s with %s" % (node.op, left.name, right.name),
                           node.line, node.col, node.span)

    # -- calls -----------------------------------------------------------
    def expr_Call(self, node, expected=None):
        # A call returning several values is only usable in a declaration,
        # assignment, return, or another call that expects a tuple.
        self.check_call(node)
        return node.ty

    def check_call(self, node):
        name = node.name
        if name == "alloc" and node.args:
            for arg in node.args[1:]:
                self.expr(arg)
        else:
            for arg in node.args:
                self.expr(arg)
        if "." in name:
            node.ty = self.check_qualified_call(node)
            return node.ty
        # Inside a namespace body, sibling functions take the shared namespace
        # parameters implicitly (`add()` in calc means `calc.add(a, b)`).
        current = self.current_fn
        if current is not None and getattr(current, "namespace", None):
            key = "%s.%s" % (current.namespace, name)
            if key in self.ns_functions:
                prefix = []
                for pname in [p.name for p in current.params[:current.shared_count]]:
                    var = self.lookup(pname)
                    if var is None:
                        continue
                    implicit = Name(pname, node.line, node.col, len(pname))
                    implicit.ty = var.ty
                    implicit.var = var
                    prefix.append(implicit)
                node.args = prefix + node.args
                node.ty = self.select_function(node, self.ns_functions, key)
                return node.ty
        if name in BUILTINS:
            node.ty = self.check_builtin(node)
            node.builtin = BUILTINS[name]
            return node.ty
        node.ty = self.select_function(node, self.functions, None)
        return node.ty

    def check_qualified_call(self, node):
        namespace = self.resolve_ns_alias(node.name.partition(".")[0])
        member = node.name.partition(".")[2]
        if namespace in self.namespaces:
            return self.select_function(node, self.ns_functions,
                                        "%s.%s" % (namespace, member))
        if namespace in _STD_NAMESPACES or namespace == "math":
            return self.check_std_call(node, namespace, member)
        raise CompileError("'%s' is not a standard library namespace" % namespace,
                           node.line, node.col, node.span)

    def select_function(self, node, table, override_name):
        name = override_name or node.name
        overloads = list(table.get(name, []))
        if not overloads and not override_name:
            overloads = list(self.generic_functions.get(name, []))
            if overloads:
                return self.instantiate_generic_matching(node, overloads)
        if not overloads and not override_name:
            # Try generic functions even when a non-generic overload exists but
            # does not match.
            generics = list(self.generic_functions.get(name, []))
            if generics:
                try:
                    return self.instantiate_generic_matching(node, generics)
                except CompileError:
                    pass
            if name in _RESERVED_C:
                raise CompileError("'%s' is reserved (it collides with the C runtime)" % name,
                                   node.line, node.col, node.span)
            raise CompileError("'%s' is not defined" % name, node.line, node.col, node.span)
        if not overloads:
            raise CompileError("'%s' is not defined in namespace '%s'"
                               % (node.name, node.name.partition(".")[0]),
                               node.line, node.col, node.span)
        matches = []
        problems = []
        for fn in overloads:
            if len(fn.params) != len(node.args):
                problems.append("%d argument(s)" % len(fn.params))
                continue
            ok = True
            for arg, param in zip(node.args, fn.params):
                pty = self.resolve_type(param.ty, fn.line, fn.col)
                if not (arg.ty == pty or T.can_auto_convert(arg.ty, pty)
                        or self._literal_fits(arg, pty)):
                    if isinstance(arg, BraceLit):
                        try:
                            self.expr(arg, pty)
                        except CompileError:
                            ok = False
                            break
                        if arg.ty == pty:
                            continue
                    ok = False
                    break
            if ok:
                matches.append(fn)
        if not matches:
            generics = list(self.generic_functions.get(node.name, []))
            if generics:
                try:
                    return self.instantiate_generic_matching(node, generics)
                except CompileError:
                    pass
            expected = " or ".join(problems) if problems else \
                " or ".join("(%s)" % ", ".join(p.ty.name for p in fn.params) for fn in overloads)
            raise CompileError("'%s' does not take (%s); it takes %s"
                               % (node.name, ", ".join(a.ty.name for a in node.args), expected),
                               node.line, node.col, node.span)
        if len(matches) > 1:
            exact = [fn for fn in matches
                     if all(a.ty == self.resolve_type(p.ty, fn.line, fn.col)
                            for a, p in zip(node.args, fn.params))]
            if len(exact) == 1:
                matches = exact
        if len(matches) > 1:
            raise CompileError("'%s' is ambiguous for (%s)"
                               % (node.name, ", ".join(a.ty.name for a in node.args)),
                               node.line, node.col, node.span)
        fn = matches[0]
        for arg, param in zip(node.args, fn.params):
            pty = self.resolve_type(param.ty, fn.line, fn.col)
            if isinstance(arg, BraceLit) and arg.ty != pty:
                self.expr(arg, pty)
            self.assignable(arg, pty, "argument")
        node.target = fn
        node.ty = fn.ret if fn.ret is not None else T.VOID
        if fn.rets:
            node.ty = fn.rets[0] if len(fn.rets) == 1 else T.tuple_type(fn.rets)
        return node.ty

    def instantiate_generic_matching(self, node, templates):
        best = None
        last_error = None
        for template in templates:
            if len(template.params) != len(node.args):
                continue
            env = {}
            try:
                if node.type_args:
                    explicit = [self.resolve_type(t, node.line, node.col)
                                for t in node.type_args]
                    if len(explicit) != len(template.type_params):
                        raise CompileError("'%s' takes %d type argument%s"
                                           % (template.name, len(template.type_params),
                                              "" if len(template.type_params) == 1 else "s"),
                                           node.line, node.col)
                    env = {p.name: a for p, a in zip(template.type_params, explicit)}
                for arg, param in zip(node.args, template.params):
                    self.match_type(param.ty, arg.ty, env)
                for p in template.type_params:
                    if p.name not in env:
                        raise CompileError("cannot infer type parameter %s for '%s'"
                                           % (p.name, template.name),
                                           node.line, node.col, node.span)
                    if not T.constraint_ok(env[p.name], p.constraint):
                        raise CompileError("%s does not satisfy %s: %s"
                                           % (p.name, p.name, p.constraint),
                                           node.line, node.col, node.span)
                best = (template, env)
                break
            except CompileError as exc:
                last_error = exc
        if best is None:
            raise last_error or CompileError("'%s' does not match" % node.name,
                                             node.line, node.col, node.span)
        template, env = best
        key = "%s<%s>" % (template.name, ",".join(env[p.name].mangle
                                                  for p in template.type_params))
        if key in self.generic_cache:
            fn = self.generic_cache[key]
        else:
            fn = copy.deepcopy(template)
            fn.type_params = []
            fn.generic_env = env
            fn.parent_generic = template.name
            fn.c_name = "%s__%s" % (template.name,
                                    "__".join(env[p.name].mangle for p in template.type_params))
            fn.rets = [T.substitute(t, env) if t is not None else None for t in template.rets]
            fn.ret = fn.rets[0] if len(fn.rets) == 1 else (T.tuple_type(fn.rets) if fn.rets else None)
            for p in fn.params:
                p.ty = T.substitute(p.ty, env)
            fn.generic_key = key
            self.generic_cache[key] = fn
            self.functions.setdefault(template.name, []).append(fn)
            self.program.functions.append(fn)
            self.check_fn(fn)
        for arg, param in zip(node.args, fn.params):
            self.assignable(arg, param.ty, "argument")
        node.target = fn
        node.ty = fn.ret if fn.ret is not None else T.VOID
        if fn.rets:
            node.ty = fn.rets[0] if len(fn.rets) == 1 else T.tuple_type(fn.rets)
        return node.ty

    def match_type(self, pattern, actual, env):
        pattern = T.substitute(pattern, env) if pattern is not None else pattern
        if pattern is None or actual is None:
            return
        if pattern.kind in ("named", "typeparam"):
            name = pattern.name_
            if name in env:
                if env[name] != actual:
                    raise CompileError("type parameter %s is both %s and %s"
                                       % (name, env[name].name, actual.name),
                                       actual.line if hasattr(actual, "line") else 0, 1)
                return
            env[name] = actual
            return
        if pattern.kind == "pointer" and actual.kind == "pointer":
            self.match_type(pattern.elem, actual.elem, env)
            return
        if pattern.kind == "array" and actual.kind == "array" and pattern.size == actual.size:
            self.match_type(pattern.elem, actual.elem, env)
            return
        if pattern.kind == "list" and actual.kind == "list":
            self.match_type(pattern.elem, actual.elem, env)
            return
        if pattern.kind == "struct" and pattern.name_ in self.generic_structs and \
                actual.kind == "struct":
            actual_t = self.structs.get(actual.name_)
            if actual_t is not None and getattr(actual_t, "parent_generic", None) == pattern.name_:
                # infer from field types is not needed here; explicit args cover it
                pass
        if pattern != actual:
            raise CompileError("expected %s, found %s" % (pattern.name, actual.name),
                               0, 1)

    @staticmethod
    def _literal_fits(arg, ty):
        if isinstance(arg, IntLit):
            return T.fits_integer(arg.value, ty) if ty.is_int else ty.is_float
        if isinstance(arg, FloatLit):
            return ty.is_float
        return False

    # -- builtins --------------------------------------------------------
    def check_builtin(self, node):
        kind = BUILTINS[node.name]
        args = node.args
        if kind in ("print", "write"):
            for arg in args:
                if arg.ty == T.VOID:
                    raise CompileError("cannot print a void value", arg.line, arg.col)
                if arg.ty.kind in ("struct", "array", "tuple", "list", "file", "task", "pointer"):
                    raise CompileError("cannot print a %s value" % arg.ty.gloss,
                                       arg.line, arg.col)
            return T.VOID
        if kind == "input":
            self._arity(node, 0)
            return T.S
        if kind == "panic":
            self._arity(node, 1)
            if args[0].ty != T.S:
                raise CompileError("panic needs an s message, found %s" % args[0].ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            return T.VOID
        if kind == "to":
            self._arity(node, 1)
            src = args[0].ty
            name = node.name
            if name == "tos":
                if src == T.VOID:
                    raise CompileError("cannot convert a void value", args[0].line, args[0].col)
                return T.S
            target = {"toi": T.I, "tof": T.F, "tob": T.B}[name]
            if src == target or src.is_int or src.is_float or src.kind == "char":
                return target
            if name == "tof" and src.kind in ("str", "c"):
                return target
            if name == "toi" and src.kind in ("str", "c", "f"):
                return target
            if name == "tob" and src.kind in ("str", "b"):
                return target
            raise CompileError("%s cannot convert %s" % (name, src.gloss),
                               args[0].line, args[0].col, args[0].span)
        if kind == "try":
            self._arity(node, 1)
            src = args[0].ty
            if src != T.S:
                raise CompileError("%s needs an s, found %s" % (node.name, src.gloss),
                                   args[0].line, args[0].col, args[0].span)
            elem = T.I if node.name == "tryi" else T.F
            node.ty = T.tuple_type([elem, T.B])
            return node.ty
        if kind == "len":
            self._arity(node, 1)
            ty = args[0].ty
            if ty.kind not in ("array", "list", "str"):
                raise CompileError("len needs an array, list, or string, found %s" % ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            return T.I
        if kind == "push":
            self._arity(node, 2)
            ty = args[0].ty
            if ty.kind != "list":
                raise CompileError("push needs a list, found %s" % ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            self.expr(args[1], ty.elem)
            self.assignable(args[1], ty.elem, "pushed value")
            return T.VOID
        if kind == "pop":
            self._arity(node, 1)
            ty = args[0].ty
            if ty.kind != "list":
                raise CompileError("pop needs a list, found %s" % ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            return ty.elem
        if kind == "clone":
            self._arity(node, 1)
            ty = args[0].ty
            if ty.kind not in ("list", "array", "struct"):
                raise CompileError("clone needs a list, array, or struct, found %s" % ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            node.clone_ty = ty
            return ty
        if kind == "isnull":
            self._arity(node, 1)
            if args[0].ty.kind != "pointer":
                raise CompileError("isnull needs a pointer, found %s" % args[0].ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            return T.B
        if kind == "cstr":
            self._arity(node, 1)
            if args[0].ty != T.S:
                raise CompileError("cstr needs a string, found %s" % args[0].ty.gloss,
                                   args[0].line, args[0].col, args[0].span)
            return T.pointer_to(T.C)
        if kind == "alloc":
            if len(node.args) != 2:
                raise CompileError("alloc takes a type and a count", node.line, node.col)
            typ = self.type_from_expr(node.args[0])
            if typ is None:
                raise CompileError("alloc's first argument must be a type", node.line, node.col)
            self.expr(node.args[1], T.I)
            self.assignable(node.args[1], T.I, "alloc count")
            node.alloc_ty = typ
            return T.pointer_to(typ)
        if kind == "free":
            self._arity(node, 1)
            if node.args[0].ty.kind != "pointer":
                raise CompileError("free needs a pointer, found %s" % node.args[0].ty.gloss,
                                   node.args[0].line, node.args[0].col)
            return T.VOID
        if kind == "readfile":
            self._arity(node, 1)
            if node.args[0].ty != T.S:
                raise CompileError("readfile needs a path (s)", node.line, node.col)
            return T.tuple_type([T.S, T.B])
        if kind == "writefile":
            self._arity(node, 2)
            if node.args[0].ty != T.S or node.args[1].ty != T.S:
                raise CompileError("writefile needs a path and a string", node.line, node.col)
            return T.B
        if kind == "fopen":
            self._arity(node, 2)
            if node.args[0].ty != T.S or node.args[1].ty != T.S:
                raise CompileError("fopen needs a path and a mode", node.line, node.col)
            node.file_mode = True
            return T.tuple_type([T.FILE, T.B])
        raise CompileError("internal: unhandled builtin %s" % node.name, node.line, node.col)

    def type_from_expr(self, node):
        if isinstance(node, Name):
            if T.is_type_name(node.name):
                return T.parse(node.name)
            t = T.named(node.name)
            resolved = self.resolve_type(t, node.line, node.col)
            if resolved.kind != "int" or t.name_ != "i":
                return resolved
        return None

    def _arity(self, node, count):
        if len(node.args) != count:
            raise CompileError("'%s' takes %d argument%s, found %d"
                               % (node.name, count, "" if count == 1 else "s", len(node.args)),
                               node.line, node.col, node.span)

    # -- standard library -------------------------------------------------
    def check_std_call(self, node, namespace, member):
        args = node.args
        if namespace == "math":
            if member in STD_CONSTANTS:
                raise CompileError("'%s' is a constant, not a function" % node.name,
                                   node.line, node.col, node.span)
            if member not in MATH_MEMBERS:
                raise CompileError("'%s' is not a math member" % node.name,
                                   node.line, node.col, node.span)
            arity = MATH_MEMBERS[member]
            if len(args) != arity:
                raise CompileError("'%s' takes %d argument%s, found %d"
                                   % (node.name, arity, "" if arity == 1 else "s", len(args)),
                                   node.line, node.col, node.span)
            for arg in args:
                self.assignable(arg, T.F, "argument to '%s'" % node.name)
            node.std = ("math", member)
            return T.F

        if namespace == "str":
            arity = {"lower": 1, "upper": 1, "has": 2, "starts": 2, "ends": 2,
                     "trim": 1, "split": 2, "join": 2}
            if member not in arity:
                raise CompileError("'%s' is not a str member" % node.name,
                                   node.line, node.col, node.span)
            if len(args) != arity[member]:
                raise CompileError("'%s' takes %d argument%s, found %d"
                                   % (node.name, arity[member],
                                      "" if arity[member] == 1 else "s", len(args)),
                                   node.line, node.col, node.span)
            if member in ("lower", "upper", "trim"):
                self.expect_type(args, 0, T.S, node)
                node.std = ("str", member)
                return T.S
            if member in ("has", "starts", "ends"):
                self.expect_type(args, 0, T.S, node)
                self.expect_type(args, 1, T.S, node)
                node.std = ("str", member)
                return T.B
            if member == "split":
                self.expect_type(args, 0, T.S, node)
                self.expect_type(args, 1, T.S, node)
                node.std = ("str", member)
                return T.list_of(T.S)
            # join
            self.expect_type(args, 1, T.S, node)
            list_ty = args[0].ty
            if not (list_ty.kind in ("list", "array") and list_ty.element_type() == T.S):
                raise CompileError("str.join needs s[] and a separator", node.line, node.col)
            node.std = ("str", member)
            return T.S

        if namespace == "list":
            if member not in ("sort", "reverse", "indexof"):
                raise CompileError("'%s' is not a list member" % node.name,
                                   node.line, node.col, node.span)
            if not args or args[0].ty.kind not in ("list", "array"):
                raise CompileError("list.%s needs a list" % member, node.line, node.col)
            elem = args[0].ty.element_type()
            if member == "indexof":
                self._arity(node, 2)
                self.expr(args[1], elem)
                self.assignable(args[1], elem, "indexof value")
                node.std = ("list", member, elem)
                return T.tuple_type([T.I, T.B])
            self._arity(node, 1)
            if not (elem.is_numeric or elem.kind in ("char", "str")) and elem.kind != "array":
                raise CompileError("list.%s needs ordered elements" % member,
                                   node.line, node.col)
            node.std = ("list", member, elem)
            return T.VOID

        if namespace == "rand":
            if member == "int":
                self._arity(node, 2)
                self.expect_type(args, 0, T.I, node)
                self.expect_type(args, 1, T.I, node)
                node.std = ("rand", "int")
                return T.I
            if member == "float":
                self._arity(node, 0)
                node.std = ("rand", "float")
                return T.F
            if member == "seed":
                self._arity(node, 1)
                self.assignable(args[0], T.I, "seed")
                node.std = ("rand", "seed")
                return T.VOID
            raise CompileError("'%s' is not a rand member" % node.name,
                               node.line, node.col, node.span)

        if namespace == "time":
            if member not in ("now", "tick"):
                raise CompileError("'%s' is not a time member" % node.name,
                                   node.line, node.col, node.span)
            self._arity(node, 0)
            node.std = ("time", member)
            return T.I

        if namespace == "fs":
            if member == "exists":
                self._arity(node, 1)
                self.expect_type(args, 0, T.S, node)
                node.std = ("fs", "exists")
                return T.B
            if member == "list":
                self._arity(node, 1)
                self.expect_type(args, 0, T.S, node)
                node.std = ("fs", "list")
                return T.tuple_type([T.list_of(T.S), T.B])
            if member == "mkdir":
                self._arity(node, 1)
                self.expect_type(args, 0, T.S, node)
                node.std = ("fs", "mkdir")
                return T.B
            if member == "remove":
                self._arity(node, 1)
                self.expect_type(args, 0, T.S, node)
                node.std = ("fs", "remove")
                return T.B
            if member == "err":
                self._arity(node, 0)
                node.std = ("fs", "err")
                return T.S
            raise CompileError("'%s' is not an fs member" % node.name,
                               node.line, node.col, node.span)

        if namespace == "task":
            if member == "spawn":
                self._arity(node, 1)
                if not isinstance(args[0], (Call, MethodCall)):
                    raise CompileError("task.spawn needs a function call", node.line, node.col)
                spawned_ty = args[0].ty
                node.spawn_ty = spawned_ty
                node.std = ("task", "spawn")
                return T.TASK
            if member == "wait":
                self._arity(node, 1)
                self.assignable(args[0], T.I, "wait time")
                node.std = ("task", "wait")
                return T.VOID
            if member == "join":
                self._arity(node, 1)
                if args[0].ty.kind != "task":
                    raise CompileError("task.join needs a Task", node.line, node.col)
                node.std = ("task", "join")
                return T.I
            if member == "stop":
                self._arity(node, 1)
                if args[0].ty.kind != "task":
                    raise CompileError("task.stop needs a Task", node.line, node.col)
                node.std = ("task", "stop")
                return T.VOID
            raise CompileError("'%s' is not a task member" % node.name,
                               node.line, node.col, node.span)

        raise CompileError("'%s' is not a standard library member" % node.name,
                           node.line, node.col, node.span)

    def expect_type(self, args, index, ty, node):
        if index >= len(args):
            raise CompileError("'%s' needs more arguments" % node.name,
                               node.line, node.col)
        self.assignable(args[index], ty, "argument to '%s'" % node.name)

    def check_file_method(self, node, ty):
        name = node.name
        args = node.args
        if name == "write":
            self._arity(node, 1)
            self.expect_type(args, 0, T.S, node)
            return T.B
        if name == "line":
            self._arity(node, 0)
            return T.tuple_type([T.S, T.B])
        if name == "read":
            self._arity(node, 1)
            self.assignable(args[0], T.I, "read size")
            return T.S
        if name == "close":
            self._arity(node, 0)
            return T.VOID
        if name == "seek":
            self._arity(node, 1)
            self.assignable(args[0], T.I, "seek position")
            return T.B
        if name == "tell":
            self._arity(node, 0)
            return T.I
        raise CompileError("File has no method '%s'" % name, node.line, node.col, node.span)


def fmt_int(value):
    return str(value)


def ends_with_return(block):
    if not block.stmts:
        return False
    last = block.stmts[-1]
    if isinstance(last, Return):
        return True
    if isinstance(last, If):
        if last.otherwise is None:
            return False
        return ends_with_return(last.otherwise) and all(ends_with_return(b) for _, b in last.branches)
    if isinstance(last, Match):
        return all(ends_with_return(a.body) for a in last.arms) and \
            any(a.patterns is None for a in last.arms)
    return False


def check(program, reporter, filename):
    return Checker(program, reporter, filename).run()
