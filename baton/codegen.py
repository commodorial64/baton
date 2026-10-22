"""AST -> C (specification sections 16 and 17 conventions)."""

from . import types as T
from .ast_nodes import (
    Assign, Binary, Block, BoolLit, Break, Call, Cast, CharLit, Continue, ExprStmt,
    FloatLit, FnDecl, ForRange, If, IntLit, Loop, Name, Return, StrLit, Unary,
    VarDecl, While,
)
from .runtime import prelude

_ESCAPE_C = {
    "\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r", "\0": "\\0",
}

_CMP_OP = {"==": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}

_MATH_C = {
    "sqrt": "sqrt", "abs": "fabs", "floor": "floor", "ceil": "ceil",
    "round": "round", "min": "fmin", "max": "fmax", "sin": "sin",
    "cos": "cos", "tan": "tan", "atan": "atan", "atan2": "atan2",
    "pow": "pow", "exp": "exp", "log": "log",
}

_MATH_CONSTANTS = {
    "math.pi": "3.14159265358979323846",
    "math.e": "2.71828182845904523536",
}


_SIDE_EFFECT_OPS = ("/", "%", "**")


def _has_side_effect(node):
    """True when evaluating this expression emits setup lines or calls out.

    Those are the cases whose order must be pinned, because C would otherwise be
    free to evaluate sibling arguments right to left.
    """
    if isinstance(node, Call):
        return True
    if isinstance(node, Binary):
        if node.op in _SIDE_EFFECT_OPS:
            return True
        return _has_side_effect(node.left) or _has_side_effect(node.right)
    if isinstance(node, Cast):
        return _has_side_effect(node.operand)
    if isinstance(node, Unary):
        return _has_side_effect(node.operand)
    return False


def c_string(value):
    """Render a baton string as one C string literal."""
    out = ['"']
    for ch in value:
        byte = ord(ch)
        if ch in _ESCAPE_C:
            out.append(_ESCAPE_C[ch])
        elif 32 <= byte < 127:
            out.append(ch)
        else:
            out.append("\\x%02x" % byte)
            # guard against a following hex digit being swallowed
            out.append('""')
    out.append('"')
    return "".join(out)


def c_char(value):
    if value == 0:
        return "'\\0'"
    if value in (ord("'"), ord("\\")):
        return "'\\%s'" % chr(value)
    if 32 <= value < 127:
        return "'%s'" % chr(value)
    return "'\\x%02x'" % value


class Func:
    def __init__(self, decl, c_name):
        self.decl = decl
        self.c_name = c_name
        self.ret = decl.ret
        self.params = decl.params


class CodeGen:
    def __init__(self, program, filename):
        self.program = program
        self.filename = filename
        self.lines = []
        self.indent = 0
        self.tmp = 0
        self.funcs = {}          # baton name -> Func
        self.loop_counter = 0
        self.loop_stack = []     # dicts: {id, label, kind, break_label, next_label}
        self.globals = {}        # name -> VarDecl + c name
        self.deferred = []       # statements for bt_init()
        self.uses_math = False

    # -- output helpers --------------------------------------------------
    def emit(self, text=""):
        if text:
            self.lines.append("    " * self.indent + text)
        else:
            self.lines.append("")

    def fresh(self, prefix="bt_t"):
        self.tmp += 1
        return "%s%d" % (prefix, self.tmp)

    # -- driver ----------------------------------------------------------
    def run(self):
        self.prepare_globals()
        self.prepare_functions()
        body = []
        self.emit(prelude())
        self.emit()
        self.emit("/* -- program ---------------------------------------------------------- */")
        self.emit()
        self.emit_globals()
        self.emit_namespace_constants()
        self.emit_prototypes()
        self.emit("static void bt_init(void);")
        self.emit()
        # function bodies
        for fn in self.all_functions():
            self.gen_fn(fn)
            self.emit()
        self.emit_init()
        self.emit_main_wrapper()
        return "\n".join(self.lines) + "\n"

    def all_functions(self):
        for ns in self.program.namespaces:
            for fn in ns.functions:
                yield fn
        for fn in self.program.functions:
            yield fn

    def prepare_globals(self):
        seen = {}
        for g in self.program.globals:
            name = g.names[0]
            seen[name] = g
        self.globals = seen

    def prepare_functions(self):
        counts = {}
        for fn in self.program.functions:
            base = fn.name
            counts[base] = counts.get(base, 0) + 1
            if base == "main":
                c_name = "bt_main"  # the C entry point is generated separately
            elif counts[base] == 1:
                c_name = base
            else:
                c_name = "%s__%d" % (base, counts[base])
            fn.c_name = c_name
            self.funcs.setdefault(base, []).append(Func(fn, c_name))
        for ns in self.program.namespaces:
            ns_counts = {}
            for fn in ns.functions:
                base = "%s_%s" % (ns.name, fn.name)
                ns_counts[base] = ns_counts.get(base, 0) + 1
                if ns_counts[base] == 1:
                    c_name = base
                else:
                    c_name = "%s__%d" % (base, ns_counts[base])
                fn.c_name = c_name

    def emit_globals(self):
        for name, g in self.globals.items():
            if g.is_const:
                value = g.values[0]
                self.emit("static const %s %s = %s;" % (g.ty.c_name, name, self.const_expr(value)))
            elif g.values and self.is_static_init(g.values[0]):
                self.emit("static %s %s = %s;" % (g.ty.c_name, name, self.const_expr(g.values[0])))
            else:
                self.emit("static %s %s;" % (g.ty.c_name, name))
                if g.values:
                    self.deferred.append(g)
        if self.globals:
            self.emit()

    def is_static_init(self, node):
        return isinstance(node, (IntLit, FloatLit, StrLit, CharLit, BoolLit))

    def const_expr(self, node):
        if isinstance(node, IntLit):
            return self.int_text(node, node.ty)
        if isinstance(node, FloatLit):
            return self.float_text(node.value, node.ty)
        if isinstance(node, StrLit):
            return c_string(node.value)
        if isinstance(node, CharLit):
            return c_char(node.value)
        if isinstance(node, BoolLit):
            return "true" if node.value else "false"
        return "0"

    def int_text(self, node, ty):
        value = node.value
        if ty is not None and ty.is_unsigned_int:
            return str(value & ((1 << ty.bits) - 1))
        if ty is not None and ty.is_int and ty.bits < 64:
            lo, hi = T.signed_range(ty.bits)
            if value > hi:
                value = ((value - lo) % (1 << ty.bits)) + lo
        return str(value)

    def float_text(self, value, ty):
        if ty is not None and ty.bits == 32:
            return "((float)%r)" % value
        return repr(value)

    def emit_prototypes(self):
        for fn in self.all_functions():
            self.emit("%s;" % self.signature(fn))
        self.emit()

    def emit_namespace_constants(self):
        for ns in self.program.namespaces:
            emitted = False
            for g in ns.constants:
                if len(g.names) != 1 or len(g.values) != 1:
                    continue
                name = "%s_%s" % (ns.name, g.names[0])
                self.emit("static const %s %s = %s;"
                          % (g.ty.c_name, name, self.const_expr(g.values[0])))
                emitted = True
            if emitted:
                self.emit()

    def signature(self, fn):
        params = ", ".join("%s %s" % (p.ty.c_name, p.name) for p in fn.params)
        ret = "void" if fn.ret is None else fn.ret.c_name
        return "%s %s(%s)" % (ret, fn.c_name, params)

    # -- functions -------------------------------------------------------
    def gen_fn(self, fn):
        self.indent = 0
        params = ", ".join("%s %s" % (p.ty.c_name, p.name) for p in fn.params)
        ret = "void" if fn.ret is None else fn.ret.c_name
        self.emit("%s %s(%s) {" % (ret, fn.c_name, params))
        self.indent += 1
        for s in fn.body.stmts:
            self.stmt(s)
        if fn.ret is not None and not fn.body.stmts:
            self.emit("return %s;" % fn.ret.zero)
        if fn.ret is not None and not _ends_with_return(fn.body.stmts):
            self.emit("return %s;  /* control reached the end */" % fn.ret.zero)
        if fn.ret is None and not fn.body.stmts:
            self.emit(";")
        self.indent -= 1
        self.emit("}")

    def emit_init(self):
        self.emit("static void bt_init(void) {")
        self.indent += 1
        if not self.deferred:
            self.emit("(void)0;")
        for g in self.deferred:
            self.emit_set_name(g.names[0], self.expr(g.values[0]))
        self.indent -= 1
        self.emit("}")
        self.emit()

    def emit_main_wrapper(self):
        self.emit("int main(void) {")
        self.indent += 1
        self.emit("bt_init();")
        main = getattr(self.program, "main", None)
        if main is not None:
            self.emit("return (int)bt_main();")
        else:
            self.emit("return 0;")
        self.indent -= 1
        self.emit("}")

    # -- statements ------------------------------------------------------
    def stmt(self, node):
        method = getattr(self, "stmt_" + type(node).__name__)
        method(node)

    def stmt_Block(self, node):
        self.emit("{")
        self.indent += 1
        if not node.stmts:
            self.emit(";")
        for s in node.stmts:
            self.stmt(s)
        self.indent -= 1
        self.emit("}")

    def stmt_VarDecl(self, node):
        pieces = []
        for i, name in enumerate(node.names):
            value = node.values[i] if i < len(node.values) else None
            if value is None:
                pieces.append("%s = %s" % (name, node.ty.zero))
            else:
                pieces.append("%s = %s" % (name, self.expr(value)))
        self.emit("%s %s;" % (node.ty.c_name, ", ".join(pieces)))

    def stmt_Assign(self, node):
        if len(node.targets) == 1 and node.ops[0] != "=":
            target = node.targets[0].name
            op = node.ops[0][:-1]  # strip '='
            self.emit_compound(target, op, node.values[0], node)
            return
        temps = []
        for i, value in enumerate(node.values):
            text = self.expr(value)
            tmp = self.fresh()
            self.emit("%s %s = %s;" % (value.ty.c_name, tmp, text))
            temps.append(tmp)
        for target, tmp in zip(node.targets, temps):
            self.emit_set_name(target.name, tmp)

    def emit_set_name(self, name, text):
        self.emit("%s = %s;" % (name, text))

    def emit_compound(self, target, op, value, node):
        ty = value.ty
        if op == "**":
            if node.targets[0].ty.is_int:
                self.emit("%s = bt_ipow(%s, %s);" % (target, target, self.expr(value)))
            else:
                self.emit("%s = bt_fpow(%s, %s);" % (target, target, self.expr(value)))
            return
        if op in ("/", "%") and node.targets[0].ty.is_int:
            rhs = self.fresh()
            self.emit("%s %s = %s;" % (ty.c_name, rhs, self.expr(value)))
            self.emit("bt_line = %d;" % node.line)
            self.emit("bt_div_check((int64_t)%s);" % rhs)
            self.emit("%s %s= %s;" % (target, op, rhs))
            return
        self.emit("%s %s= %s;" % (target, op, self.expr(value)))

    def stmt_ExprStmt(self, node):
        self.emit_expr_stmt(node.expr)

    def emit_expr_stmt(self, node):
        if isinstance(node, Call):
            self.emit("%s;" % self.gen_expr(node))
            return
        self.emit("%s;" % self.expr(node))

    def stmt_If(self, node):
        # Evaluate every condition up front into a bool temporary, so the
        # division checks and other setup of a later `elf` never run when an
        # earlier branch already matched (and land before the chain, not inside it).
        rendered = []
        for cond, body in node.branches:
            text, setup = self.render_to(cond)
            for line in setup:
                self.lines.append(line)
            if setup:
                flag = self.fresh("bt_cond")
                self.emit("bool %s = %s;" % (flag, text))
                text = flag
            rendered.append((text, body))

        for i, (cond_text, body) in enumerate(rendered):
            self.emit(("if (%s) {" if i == 0 else "} else if (%s) {") % cond_text)
            self.indent += 1
            for s in body.stmts:
                self.stmt(s)
            if not body.stmts:
                self.emit(";")
            self.indent -= 1
        if node.otherwise is not None:
            self.emit("} else {")
            self.indent += 1
            for s in node.otherwise.stmts:
                self.stmt(s)
            if not node.otherwise.stmts:
                self.emit(";")
            self.indent -= 1
        self.emit("}")

    def stmt_While(self, node):
        info = self.enter_loop(node, "while")
        cond_text, setup = self.render_to(node.cond)
        for line in setup:
            self.lines.append(line)
        if info["long"]:
            self.emit("{")
            self.indent += 1
            self.emit("while (%s) {" % cond_text)
            self.indent += 1
            self.emit_body(node.body)
            self.emit("%s_next: ;" % info["c_label"])
            self.indent -= 1
            self.emit("}")
            self.emit("%s_break: ;" % info["c_label"])
            self.indent -= 1
            self.emit("}")
        else:
            self.emit("while (%s) {" % cond_text)
            self.indent += 1
            self.emit_body(node.body)
            self.indent -= 1
            self.emit("}")
        self.exit_loop(info, node)

    def stmt_ForRange(self, node):
        info = self.enter_loop(node, "for")
        ty = node.var_ty.c_name
        name = node.var
        lo = self.fresh("bt_lo")
        hi = self.fresh("bt_hi")
        step = self.fresh("bt_step")
        self.emit("{")
        self.indent += 1
        self.emit("%s %s = %s;" % (ty, lo, self.expr(node.start)))
        self.emit("%s %s = %s;" % (ty, hi, self.expr(node.end)))
        if node.step is not None:
            self.emit("%s %s = %s;" % (ty, step, self.expr(node.step)))
        else:
            self.emit("%s %s = 1;" % (ty, step))
        cmp_up = "<=" if node.inclusive else "<"
        cmp_down = ">=" if node.inclusive else ">"
        if info["long"]:
            # a `for` whose continue-point must move the counter: a while form
            self.emit("%s %s = %s;" % (ty, name, lo))
            cond = "%s > 0 ? (%s %s %s) : (%s %s %s)" % (step, name, cmp_up, hi,
                                                          name, cmp_down, hi)
            self.emit("while (%s) {" % cond)
            self.indent += 1
            self.emit_body(node.body)
            self.emit("%s_next: ;" % info["c_label"])
            self.emit("%s += %s;" % (name, step))
            self.indent -= 1
            self.emit("}")
            self.emit("%s_break: ;" % info["c_label"])
        else:
            self.emit("for (%s %s = %s; %s > 0 ? (%s %s %s) : (%s %s %s); %s += %s) {"
                      % (ty, name, lo, step, name, cmp_up, hi, name, cmp_down, hi, name, step))
            self.indent += 1
            self.emit_body(node.body)
            self.indent -= 1
            self.emit("}")
        self.indent -= 1
        self.emit("}")
        self.exit_loop(info, node)

    def stmt_Loop(self, node):
        info = self.enter_loop(node, "loop")
        if info["long"]:
            self.emit("{")
            self.indent += 1
            self.emit("for (;;) {")
            self.indent += 1
            self.emit_body(node.body)
            self.emit("%s_next: ;" % info["c_label"])
            self.indent -= 1
            self.emit("}")
            self.emit("%s_break: ;" % info["c_label"])
            self.indent -= 1
            self.emit("}")
        else:
            self.emit("for (;;) {")
            self.indent += 1
            self.emit_body(node.body)
            self.indent -= 1
            self.emit("}")
        self.exit_loop(info, node)

    def find_loop(self, label):
        for info in reversed(self.loop_stack):
            if info["node"].label == label:
                return info
        return None

    def stmt_Break(self, node):
        if node.label is None:
            self.emit("break;")
        else:
            self.emit("goto %s_break;" % self.find_loop(node.label)["c_label"])

    def stmt_Continue(self, node):
        if node.label is None:
            info = self.loop_stack[-1]
            if info["long"]:
                self.emit("goto %s_next;" % info["c_label"])
            else:
                self.emit("continue;")
        else:
            self.emit("goto %s_next;" % self.find_loop(node.label)["c_label"])

    def stmt_Return(self, node):
        if node.value is None:
            self.emit("return;")
        else:
            self.emit("return %s;" % self.expr(node.value))

    def emit_body(self, block):
        if not block.stmts:
            self.emit(";")
        for s in block.stmts:
            self.stmt(s)

    # -- loop bookkeeping -------------------------------------------------
    def enter_loop(self, node, kind):
        self.loop_counter += 1
        c_label = "bt_lblk%d" % self.loop_counter
        long_form = bool(node.label)
        info = {"c_label": c_label, "node": node, "kind": kind, "long": long_form}
        self.loop_stack.append(info)
        return info

    def exit_loop(self, info, node):
        self.loop_stack.pop()

    # -- expressions -----------------------------------------------------
    def expr(self, node):
        """Render an expression whose side effects (temporaries) go in the main line list."""
        return self._render(node)

    def render_to(self, node):
        """Render an expression, capturing any emitted lines in the returned buffer.

        Conditions and other contexts where the value is needed inline use this so
        that division checks land before the statement that consumes the value.
        """
        saved = self.lines
        self.lines = []
        text = self._render(node)
        captured = self.lines
        self.lines = saved
        return text, captured

    def _render(self, node):
        text = self.gen_expr(node)
        target = getattr(node, "coerce_to", None)
        if target is not None and target != node.ty:
            return "(%s)(%s)" % (target.c_name, text)
        return text

    def gen_expr(self, node):
        method = getattr(self, "gen_" + type(node).__name__)
        return method(node)

    def gen_IntLit(self, node):
        return self.int_text(node, node.ty)

    def gen_FloatLit(self, node):
        return self.float_text(node.value, node.ty)

    def gen_StrLit(self, node):
        return c_string(node.value)

    def gen_CharLit(self, node):
        return c_char(node.value)

    def gen_BoolLit(self, node):
        return "true" if node.value else "false"

    def gen_Name(self, node):
        if getattr(node, "c_name", None):
            return node.c_name
        constant = _MATH_CONSTANTS.get(node.name)
        if constant is not None:
            return constant
        return node.name

    def gen_Unary(self, node):
        operand = self.expr(node.operand)
        if node.op == "not":
            return "(!%s)" % operand
        return "(%s%s)" % (node.op, operand)

    def gen_Cast(self, node):
        return "((%s)%s)" % (node.target.c_name, self.expr(node.operand))

    def gen_Binary(self, node):
        op = node.op
        if op == "and":
            return "(%s && %s)" % (self.expr(node.left), self.expr(node.right))
        if op == "or":
            return "(%s || %s)" % (self.expr(node.left), self.expr(node.right))
        if op == "**":
            left = self.expr(node.left)
            right = self.expr(node.right)
            if node.ty.is_int:
                return "bt_ipow(%s, %s)" % (left, right)
            return "bt_fpow(%s, %s)" % (left, right)
        left_ty = node.left.ty
        if op == "+" and left_ty == T.S:
            return "bt_str_cat(%s, %s)" % (self.expr(node.left), self.expr(node.right))
        if op in ("/", "%") and node.ty.is_int:
            return self.gen_division(node, op)
        if left_ty == T.S and op in ("==", "!=", "<", "<=", ">", ">="):
            return "bt_str_cmp(%s, %s) %s 0" % (self.expr(node.left),
                                                self.expr(node.right),
                                                _CMP_OP[op])
        return "(%s %s %s)" % (self.expr(node.left), op, self.expr(node.right))

    def gen_division(self, node, op):
        left = self.fresh()
        right = self.fresh()
        self.emit("%s %s = %s;" % (node.ty.c_name, left, self.expr(node.left)))
        self.emit("%s %s = %s;" % (node.ty.c_name, right, self.expr(node.right)))
        self.emit("bt_line = %d;" % node.line)
        self.emit("bt_div_check((int64_t)%s);" % right)
        return "(%s %s %s)" % (left, op, right)

    def gen_Call(self, node):
        if getattr(node, "builtin", None):
            return self.gen_builtin(node)
        if getattr(node, "std", None):
            return self.gen_std_call(node)
        args = ", ".join(self.hoist(a) for a in node.args)
        name = node.target.c_name
        return "%s(%s)" % (name, args)

    def gen_std_call(self, node):
        _, member = node.std
        args = ", ".join(self.hoist(a) for a in node.args)
        return "%s(%s)" % (_MATH_C[member], args)

    def hoist(self, node):
        """Evaluate an argument in source order into a temporary.

        C leaves argument evaluation order unspecified (gcc goes right to left),
        so any expression with a side effect is pinned to a temp first, which
        makes baton's calls left to right.
        """
        text = self.expr(node)
        if not _has_side_effect(node):
            return text
        temp = self.fresh("bt_arg")
        self.emit("%s %s = %s;" % (node.ty.c_name, temp, text))
        return temp

    # -- builtins --------------------------------------------------------
    def gen_builtin(self, node):
        kind = node.builtin
        if kind in ("print", "write"):
            return self.gen_print(node, newline=(kind == "print"))
        if kind == "input":
            return "bt_input()"
        if kind == "panic":
            self.emit("bt_line = %d;" % node.line)
            return "bt_panic(%s, %d)" % (self.expr(node.args[0]), node.line)
        return self.gen_to(node)

    def gen_print(self, node, newline):
        if not node.args:
            return "putchar('\\n')" if newline else "(void)0"
        fmt_parts = []
        args = []
        for arg in node.args:
            ty = arg.ty
            text = self.hoist(arg)
            if ty == T.S:
                fmt_parts.append("%s")
                args.append(text)
            elif ty.is_float:
                fmt_parts.append("%.17g")
                args.append("(double)(%s)" % text)
            elif ty.kind == "char":
                fmt_parts.append("%c")
                args.append(text)
            elif ty.is_signed_int:
                fmt_parts.append("%lld")
                args.append("(long long)(%s)" % text)
            elif ty.is_unsigned_int:
                fmt_parts.append("%llu")
                args.append("(unsigned long long)(%s)" % text)
            elif ty == T.B:
                fmt_parts.append("%s")
                args.append("((%s) ? \"true\" : \"false\")" % text)
            else:
                fmt_parts.append("%s")
                args.append(text)
        fmt = " ".join(fmt_parts)
        if newline:
            fmt += "\\n"
        call = 'printf("%s"%s)' % (fmt, (", " + ", ".join(args)) if args else "")
        return call

    def gen_to(self, node):
        name = node.name
        src = node.args[0]
        src_ty = src.ty
        text = self.expr(src)
        if name == "tos":
            if src_ty == T.S:
                return text
            if src_ty == T.B:
                return "bt_tos_b(%s)" % text
            if src_ty.is_float:
                return "bt_tos_f((double)(%s))" % text
            if src_ty.kind == "char":
                return "bt_tos_c(%s)" % text
            return "bt_tos_i((int64_t)(%s))" % text
        if name == "toi":
            if src_ty == T.S:
                return "bt_toi(%s)" % text
            return "((int64_t)(%s))" % text
        if name == "tof":
            if src_ty == T.S:
                return "bt_tof(%s)" % text
            return "((double)(%s))" % text
        if name == "tob":
            if src_ty == T.S:
                return "bt_tob(%s)" % text
            return text
        return text


def _ends_with_return(stmts):
    from .checker import ends_with_return
    from .ast_nodes import Block, If, Return
    if not stmts:
        return True  # an empty body gets a zero return, which is fine
    last = stmts[-1]
    if isinstance(last, Return):
        return True
    if isinstance(last, If):
        if last.otherwise is None:
            return False
        return (ends_with_return(last.otherwise)
                and all(ends_with_return(b) for _, b in last.branches))
    return False


def generate(program, filename="<source>"):
    return CodeGen(program, filename).run()
