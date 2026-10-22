"""Type checking (specification sections 3, 4, 5, 7, 8, 10, 17)."""

from . import types as T
from .ast_nodes import (
    Assign, Binary, Block, BoolLit, Break, Call, Cast, CharLit, Continue, ExprStmt,
    FloatLit, FnDecl, ForRange, If, IntLit, Loop, Name, Return, StrLit, Unary,
    VarDecl, While,
)
from .diagnostics import CompileError

# -- builtins ------------------------------------------------------------
# kind: "print" | "write" | "input" | "panic" | "to" | "unimpl"
BUILTINS = {
    "print": "print",
    "write": "write",
    "input": "input",
    "panic": "panic",
    "tos": "to",
    "toi": "to",
    "tof": "to",
    "tob": "to",
    "tryi": "unimpl",
    "tryf": "unimpl",
    "len": "unimpl",
    "push": "unimpl",
    "pop": "unimpl",
    "clone": "unimpl",
    "isnull": "unimpl",
    "cstr": "unimpl",
    "alloc": "unimpl",
    "free": "unimpl",
    "readfile": "unimpl",
    "writefile": "unimpl",
    "fopen": "unimpl",
}

# Standard-library namespaces that are recognised but not implemented yet.
_STD_NAMESPACES = ("str", "list", "rand", "time", "fs", "task")

# The math namespace takes f arguments and returns f for every member
# (specification section 22).  Integers widen to f automatically.
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

# Widening chains for the "inferred" expression types
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
        self.functions = {}     # name -> [FnDecl]
        self.globals = {}       # name -> Var
        self.namespaces = {}    # name -> NamespaceDecl
        self.ns_functions = {}  # "ns.fn" -> [FnDecl]
        self.ns_constants = {}  # "ns.name" -> Var
        self.scopes = []        # [{name: Var}], innermost last
        self.loops = []         # stack of dicts: {label, breakable, line}
        self.current_fn = None
        self.in_top_level = True

    # -- driver ----------------------------------------------------------
    def run(self):
        self.collect_top_level()
        for g in self.program.globals:
            self.check_global(g)
        for ns in self.program.namespaces:
            self.check_namespace_constants(ns)
        for ns in self.program.namespaces:
            for fn in ns.functions:
                self.check_fn(fn)
        for fn in self.program.functions:
            self.check_fn(fn)
        self.check_main()
        return self.program

    def collect_top_level(self):
        for ns in self.program.namespaces:
            self.collect_namespace(ns)
        for fn in self.program.functions:
            if fn.name in BUILTINS:
                self.reporter.error("'%s' is a builtin and cannot be redefined" % fn.name,
                                    fn.line, fn.col)
                continue
            if fn.name in _RESERVED_C:
                self.reporter.error("'%s' is reserved (it collides with the C runtime)" % fn.name,
                                    fn.line, fn.col)
                continue
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

    @staticmethod
    def signatures_differ(existing, fn):
        sig = [(p.ty for p in fn.params), fn.ret]
        for other in existing:
            if [(p.ty for p in other.params), other.ret] == sig:
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
            else:
                self.ty = g.ty
        self.declare_global_type(g, name, value)

    def declare_global_type(self, g, name, value):
        if g.ty is None:
            g.ty = self.infer_type(value)
            self.infer_warning(g, name, value)
        elif value is not None:
            self.assignable(value, g.ty, "'%s'" % name)
        if g.is_const and value is not None and not self.is_constant(value):
            self.reporter.error("a const global needs a constant value", g.line, g.col)
        self.globals[name] = Var(g.ty, mutable=not g.is_const, const=g.is_const, line=g.line)
        g.inferred_type = g.ty

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
        if not hasattr(fn, "check"):
            self.current_fn = fn
            fn.local_vars = []
            # parameters
            self.scopes.append({})
            for p in fn.params:
                if p.name in self.scopes[-1]:
                    self.reporter.error("duplicate parameter '%s'" % p.name, p.line, p.col)
                self.scopes[-1][p.name] = Var(p.ty, True, False, p.line)
                fn.local_vars.append((p.name, p.ty))
            self.stmt(fn.body)
            self.scopes.pop()
            if fn.ret is not None and not ends_with_return(fn.body):
                self.codegen_pad = True
            fn.check = True
            self.current_fn = None

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
        if node.values:
            for v in node.values:
                self.expr(v)
        if node.ty is None:
            if not node.values:
                self.reporter.error(
                    "'%s' needs a type prefix — there is no value to infer from" % node.names[0],
                    node.line, node.col)
                node.ty = T.I
            else:
                if len(node.values) != len(node.names):
                    self.reporter.error("declaration needs one value per name",
                                        node.line, node.col)
                    node.ty = T.I
                else:
                    node.ty = self.infer_type(node.values[0])
                    self.infer_warning(node, node.names[0], node.values[0])
        for i, name in enumerate(node.names):
            value = node.values[i] if i < len(node.values) else None
            if value is not None:
                if len(node.values) == len(node.names):
                    self.assignable(value, node.ty, "'%s'" % name)
            self.declare(name, Var(node.ty, mutable=not node.is_const,
                                   const=node.is_const, line=node.line, decl=node),
                         node.line, node.col)

    def stmt_Assign(self, node):
        targets = []
        for tgt in node.targets:
            if "." in tgt.name:
                if tgt.name in STD_CONSTANTS or tgt.name in self.ns_constants:
                    self.reporter.error("'%s' is a constant and cannot be assigned"
                                        % tgt.name, tgt.line, tgt.col)
                else:
                    self.reporter.error("can only assign to a variable", tgt.line, tgt.col)
                targets.append(None)
                continue
            var = self.lookup(tgt.name)
            if var is None:
                self.reporter.error("'%s' is not declared" % tgt.name, tgt.line, tgt.col)
                targets.append(None)
                continue
            if not var.mutable:
                self.reporter.error("'%s' is const and cannot be assigned" % tgt.name,
                                    tgt.line, tgt.col)
            targets.append(var)
        for v in node.values:
            self.expr(v)
        for i, var in enumerate(targets):
            if var is None or i >= len(node.values):
                continue
            self.assignable(node.values[i], var.ty, "'%s'" % node.targets[i].name)

    def stmt_ExprStmt(self, node):
        self.expr(node.expr)

    def stmt_If(self, node):
        for cond, body in node.branches:
            self.expr(cond)
            self.condition(cond, "if")
            self.stmt(body)
        if node.otherwise is not None:
            self.stmt(node.otherwise)

    def stmt_While(self, node):
        self.expr(node.cond)
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
        ret = self.current_fn.ret
        if node.value is None:
            if ret is not None:
                self.reporter.error("'%s' must return a %s" % (self.current_fn.name, ret.name),
                                    node.line, node.col)
            return
        self.expr(node.value)
        if getattr(self.current_fn, "det_return", False) and ret is None:
            self.current_fn.ret = node.value.ty
            self.current_fn.det_return = False
            return
        if ret is None:
            self.reporter.error("'%s' returns nothing, but a value is given"
                                % self.current_fn.name, node.line, node.col)
            return
        self.assignable(node.value, ret, "'%s'" % self.current_fn.name)

    # -- type helpers ----------------------------------------------------
    def condition(self, node, context):
        """A condition must be exactly b (section 4: no truthiness)."""
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
        """Insert whatever conversion the target type needs, for codegen."""
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
        raise CompileError("%s is %s but must be %s" % (what, src.name, target.name),
                           node.line, node.col, node.span)

    def infer_warning(self, decl, name, value):
        ty = self.infer_type(value)
        # An inferred declaration whose value is an untyped literal gets the
        # literal's own default type, so no warning if it already matches.
        suggestion = "%s %s %s" % (ty.name, "const" if decl.is_const else "local",
                                   ", ".join(decl.names))
        if value is not None and len(decl.names) == len(decl.values):
            suggestion += " = ?"
        self.reporter.warn(
            "no type prefix on '%s', inferred '%s' (%s)" % (name, ty.name, ty.gloss),
            decl.line, decl.col, span=None,
            hint=None)

    # -- expressions -----------------------------------------------------
    def expr(self, node):
        method = getattr(self, "expr_" + type(node).__name__, None)
        if method is None:
            raise CompileError("internal: unhandled expression %s" % type(node).__name__,
                               node.line, node.col)
        method(node)
        return node.ty

    def expr_IntLit(self, node):
        node.ty = T.I

    def expr_FloatLit(self, node):
        node.ty = T.F

    def expr_StrLit(self, node):
        node.ty = T.S

    def expr_CharLit(self, node):
        node.ty = T.C

    def expr_BoolLit(self, node):
        node.ty = T.B

    def expr_Name(self, node):
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
            if namespace in self.namespaces:
                raise CompileError("'%s' is not a constant in namespace '%s'"
                                   % (node.name, namespace), node.line, node.col, node.span)
            if namespace == "math":
                raise CompileError("'%s' is not a math constant; math has pi and e"
                                   % node.name, node.line, node.col, node.span)
            if namespace in _STD_NAMESPACES:
                raise CompileError("the %s standard namespace is not implemented in this "
                                   "build yet" % namespace, node.line, node.col, node.span)
            raise CompileError("'%s' is not a standard library name" % node.name,
                               node.line, node.col, node.span)
        var = self.lookup(node.name)
        if var is None:
            raise CompileError("'%s' is not declared" % node.name, node.line, node.col, node.span)
        node.ty = var.ty
        node.var = var

    def expr_Unary(self, node):
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
        # unary -
        if not src.is_numeric:
            raise CompileError("'-' needs a number, found %s" % src.gloss,
                               node.line, node.col, node.span)
        node.ty = src

    def expr_Cast(self, node):
        self.expr(node.operand)
        src, dst = node.operand.ty, node.target
        if src == dst:
            node.ty = dst
            return
        if src == T.B or dst == T.B or src == T.S or dst == T.S:
            raise CompileError("'as' cannot convert between %s and %s — b and s never convert"
                               % (src.gloss, dst.gloss), node.line, node.col, node.span)
        node.ty = dst

    def expr_Binary(self, node):
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

        # + - * / %
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

    def _promote_arith(self, node):
        left, right = node.left.ty, node.right.ty
        result = T.promote(left, right)
        if result is None:
            # Literal adaptation: an untyped literal takes the other side's type.
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
        if left == T.S or right == T.S:
            if left == T.S and right == T.S:
                if node.op not in ("==", "!=", "<", "<=", ">", ">="):
                    raise CompileError("'%s' cannot compare strings" % node.op,
                                       node.line, node.col, node.span)
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
    def expr_Call(self, node):
        for arg in node.args:
            self.expr(arg)
        name = node.name

        if "." in name:
            namespace = name.partition(".")[0]
            if namespace in self.namespaces:
                node.ty = self.check_ns_call(node)
            else:
                node.ty = self.check_std_call(node)
            return

        if name in BUILTINS:
            node.ty = self.check_builtin(node)
            node.builtin = BUILTINS[name]
            return

        overloads = self.functions.get(name)
        if not overloads:
            if name in _RESERVED_C:
                raise CompileError("'%s' is reserved (it collides with the C runtime)" % name,
                                   node.line, node.col, node.span)
            raise CompileError("'%s' is not defined" % name, node.line, node.col, node.span)

        matches = []
        problems = []
        for fn in overloads:
            if len(fn.params) != len(node.args):
                problems.append("%d argument(s)" % len(fn.params))
                continue
            ok = True
            for arg, param in zip(node.args, fn.params):
                if not (arg.ty == param.ty or T.can_auto_convert(arg.ty, param.ty)
                        or self._literal_fits(arg, param.ty)):
                    ok = False
                    break
            if ok:
                matches.append(fn)
        if not matches:
            expected = " or ".join(problems) if problems else \
                " or ".join("(%s)" % ", ".join(p.ty.name for p in fn.params) for fn in overloads)
            raise CompileError("'%s' does not take (%s); it takes %s"
                               % (name, ", ".join(a.ty.name for a in node.args), expected),
                               node.line, node.col, node.span)
        if len(matches) > 1:
            # Prefer overloads whose parameter types match the arguments exactly;
            # only literal adaptation and widening leave room for a tie.
            exact = [fn for fn in matches
                     if all(a.ty == p.ty for a, p in zip(node.args, fn.params))]
            if len(exact) == 1:
                matches = exact
        if len(matches) > 1:
            raise CompileError("'%s' is ambiguous for (%s)"
                               % (name, ", ".join(a.ty.name for a in node.args)),
                               node.line, node.col, node.span)
        fn = matches[0]
        for arg, param in zip(node.args, fn.params):
            self.assignable(arg, param.ty, "argument")
        node.target = fn
        node.ty = fn.ret if fn.ret is not None else T.VOID

    def check_ns_call(self, node):
        overloads = self.ns_functions.get(node.name)
        if not overloads:
            namespace = node.name.partition(".")[0]
            raise CompileError("'%s' is not defined in namespace '%s'"
                               % (node.name, namespace),
                               node.line, node.col, node.span)
        matches = []
        problems = []
        for fn in overloads:
            if len(fn.params) != len(node.args):
                problems.append("%d argument(s)" % len(fn.params))
                continue
            ok = True
            for arg, param in zip(node.args, fn.params):
                if not (arg.ty == param.ty or T.can_auto_convert(arg.ty, param.ty)
                        or self._literal_fits(arg, param.ty)):
                    ok = False
                    break
            if ok:
                matches.append(fn)
        if not matches:
            expected = " or ".join(problems) if problems else \
                " or ".join("(%s)" % ", ".join(p.ty.name for p in fn.params)
                            for fn in overloads)
            raise CompileError("'%s' does not take (%s); it takes %s"
                               % (node.name, ", ".join(a.ty.name for a in node.args),
                                  expected),
                               node.line, node.col, node.span)
        if len(matches) > 1:
            exact = [fn for fn in matches
                     if all(a.ty == p.ty for a, p in zip(node.args, fn.params))]
            if len(exact) == 1:
                matches = exact
        if len(matches) > 1:
            raise CompileError("'%s' is ambiguous for (%s)"
                               % (node.name, ", ".join(a.ty.name for a in node.args)),
                               node.line, node.col, node.span)
        fn = matches[0]
        for arg, param in zip(node.args, fn.params):
            self.assignable(arg, param.ty, "argument")
        node.target = fn
        node.ty = fn.ret if fn.ret is not None else T.VOID
        return node.ty

    def check_std_call(self, node):
        namespace, _, member = node.name.partition(".")
        if namespace in _STD_NAMESPACES:
            raise CompileError("the %s standard namespace is not implemented in this "
                               "build yet" % namespace,
                               node.line, node.col, node.span)
        if namespace != "math":
            raise CompileError("'%s' is not a standard library namespace" % namespace,
                               node.line, node.col, node.span)
        if member in STD_CONSTANTS:
            raise CompileError("'%s' is a constant, not a function" % node.name,
                               node.line, node.col, node.span)
        if member not in MATH_MEMBERS:
            raise CompileError("'%s' is not a math member" % node.name,
                               node.line, node.col, node.span)
        arity = MATH_MEMBERS[member]
        if len(node.args) != arity:
            raise CompileError("'%s' takes %d argument%s, found %d"
                               % (node.name, arity, "" if arity == 1 else "s",
                                  len(node.args)),
                               node.line, node.col, node.span)
        for arg in node.args:
            self.assignable(arg, T.F, "argument to '%s'" % node.name)
        node.std = ("math", member)
        return T.F

    @staticmethod
    def _literal_fits(arg, ty):
        if isinstance(arg, IntLit):
            return T.fits_integer(arg.value, ty) if ty.is_int else ty.is_float
        if isinstance(arg, FloatLit):
            return ty.is_float
        return False

    def check_builtin(self, node):
        kind = BUILTINS[node.name]
        args = node.args
        if kind in ("print", "write"):
            for arg in args:
                if arg.ty == T.VOID:
                    raise CompileError("cannot print a void value", arg.line, arg.col)
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
            expected = {"tos": None, "toi": (T.I, ("str", "f", "c")),
                        "tof": (T.F, ("str", "c")), "tob": (T.B, ("str", "b"))}[name]
            if name == "tos":
                if src == T.VOID:
                    raise CompileError("cannot convert a void value", args[0].line, args[0].col)
                return T.S
            target, allowed = expected
            if src == target or src.is_int or src.is_float or src.kind == "char":
                return target
            if src.kind in allowed:
                return target
            if name == "tof" and src.kind in ("str", "c"):
                return target
            raise CompileError("%s cannot convert %s" % (name, src.gloss),
                               args[0].line, args[0].col, args[0].span)
        # unimpl
        section = {
            "tryi": "checked parse functions (spec 5)", "tryf": "checked parse functions (spec 5)",
            "len": "lists (spec 12)", "push": "lists (spec 12)", "pop": "lists (spec 12)",
            "clone": "lists (spec 12)", "isnull": "pointers (spec 20)", "cstr": "pointers (spec 20)",
            "alloc": "pointers (spec 20)", "free": "pointers (spec 20)",
            "readfile": "files (spec 23)", "writefile": "files (spec 23)",
            "fopen": "files (spec 23)",
        }[node.name]
        raise CompileError("%s is not implemented in this build yet" % section,
                           node.line, node.col, node.span)

    def _arity(self, node, count):
        if len(node.args) != count:
            raise CompileError("'%s' takes %d argument%s, found %d"
                               % (node.name, count, "" if count == 1 else "s", len(node.args)),
                               node.line, node.col, node.span)


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
    return False


def check(program, reporter, filename):
    return Checker(program, reporter, filename).run()
