"""AST -> C (specification sections 16 and 17 conventions)."""

from . import types as T
from .ast_nodes import (
    AddrOf, Assign, Binary, Block, BoolLit, BraceLit, Break, Call, Cast, CharLit,
    Continue, Deref, ExprStmt, FloatLit, FnDecl, ForEach, ForRange, If, Index,
    IntLit, Loop, Match, MatchArm, Member, MethodCall, Name, RangePattern, Return,
    Slice, StrLit, Unary, VarDecl, While,
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


def _has_side_effect(node):
    if isinstance(node, (Call, MethodCall)):
        return True
    if isinstance(node, BraceLit):
        return True
    if isinstance(node, Slice):
        return True
    if isinstance(node, Binary):
        if node.op in _SIDE_EFFECT_OPS or getattr(node, "array_op", False) or node.op == "@":
            return True
        return _has_side_effect(node.left) or _has_side_effect(node.right)
    if isinstance(node, (Cast, Unary, AddrOf, Deref)):
        return _has_side_effect(node.operand)
    return False


class CodeGen:
    def __init__(self, program, filename):
        self.program = program
        self.filename = filename
        self.lines = []
        self.indent = 0
        self.tmp = 0
        self.loop_counter = 0
        self.loop_stack = []
        self.current_fn = None
        self.globals = {}
        self.deferred = []
        self.arrays = {}          # Ty -> None, insertion order
        self.tuples = {}          # Ty -> None
        self.emitted_types = set()
        self.comparators = {}     # elem mangle -> elem Ty
        self.structs = []
        self.externs = []

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
        self.scan_types(self.program)
        self.emit(prelude())
        self.emit()
        for include in getattr(self.program, "btl_includes", []) or []:
            self.emit('#include "%s"' % include)
        if getattr(self.program, "btl_includes", None):
            self.emit()
        self.emit("/* -- program types ---------------------------------------------------- */")
        self.emit_types()
        self.emit()
        self.emit("/* -- program ---------------------------------------------------------- */")
        self.emit()
        self.emit_globals()
        self.emit_namespace_constants()
        self.emit_externs()
        self.emit_prototypes()
        self.emit_helpers()
        for fn in self.all_functions():
            if fn.extern or fn.type_params:
                continue
            self.gen_fn(fn)
            self.emit()
        self.emit_init()
        self.emit_main_wrapper()
        return "\n".join(self.lines) + "\n"

    def all_functions(self):
        for fn in self.program.functions:
            yield fn
        for ns in self.program.namespaces:
            for fn in ns.functions:
                yield fn

    def prepare_globals(self):
        self.globals = {}
        for g in self.program.globals:
            if g.names:
                self.globals[g.names[0]] = g

    def prepare_functions(self):
        counts = {}
        for fn in self.program.functions:
            if fn.extern:
                fn.c_name = fn.c_name or fn.name
                self.externs.append(fn)
                continue
            if fn.type_params:
                continue
            if fn.name == "main":
                fn.c_name = "bt_main"
                continue
            if fn.parent_generic:
                if not fn.c_name:
                    fn.c_name = "bt_%s" % fn.name
                continue
            base = fn.name
            counts[base] = counts.get(base, 0) + 1
            if counts[base] == 1:
                fn.c_name = base
            else:
                fn.c_name = "%s__%d" % (base, counts[base])
        btl_externs = list(getattr(self.program, "btl_externs", []) or [])
        for ns in self.program.namespaces:
            for i, fn in enumerate(ns.functions):
                if fn.extern:
                    fn.c_name = fn.c_name or ("%s_%s" % (ns.name, fn.name))
                    if fn not in self.externs:
                        self.externs.append(fn)
                    continue
                base = "%s_%s" % (ns.name, fn.name)
                used = sum(1 for other in ns.functions[:i]
                           if other.name == fn.name and not other.extern)
                fn.c_name = base if used == 0 else "%s__%d" % (base, used + 1)
        for fn in btl_externs:
            if fn not in self.externs:
                self.externs.append(fn)
        self.structs = list(getattr(self.program, "struct_types", []) or [])

    # -- type collection -------------------------------------------------
    def scan_types(self, obj, seen=None):
        if seen is None:
            seen = set()
        if isinstance(obj, T.Ty):
            self.register_type(obj)
            return
        if obj is None or isinstance(obj, (str, int, float, bool, bytes)):
            return
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)
        if isinstance(obj, (list, tuple, set)):
            for item in obj:
                self.scan_types(item, seen)
            return
        if isinstance(obj, dict):
            for item in obj.values():
                self.scan_types(item, seen)
            return
        if hasattr(obj, "__dict__"):
            for key, value in vars(obj).items():
                if key in ("program",):
                    continue
                self.scan_types(value, seen)
        # list.sort/indexof need a comparator emitted up front.
        if isinstance(obj, (Call, MethodCall)):
            std = getattr(obj, "std", None)
            if std and std[0] == "list" and len(std) > 2:
                elem = std[2]
                self.comparators[elem.mangle] = elem

    def register_type(self, ty):
        if ty is None:
            return
        if ty.kind == "array":
            self.register_type(ty.elem)
            self.arrays.setdefault(ty, None)
        elif ty.kind == "tuple":
            for elem in ty.elems:
                self.register_type(elem)
            self.tuples.setdefault(ty, None)
        elif ty.kind in ("pointer", "list"):
            self.register_type(ty.elem if ty.kind == "pointer" else ty.elem)

    def emit_types(self):
        self.struct_by_name = {getattr(s, "c_name", s.name) or s.name: s
                               for s in self.structs}
        for s in self.structs:
            self.emit("typedef struct %s %s;" % (s.c_name, s.c_name))
        if self.structs:
            self.emit()
        # Emit structs, arrays and tuples in dependency order.  A struct that
        # contains an array needs the array typedef, while an array of structs
        # needs the struct definition, so a flat list is not enough.
        self.emitting = set()
        for s in self.structs:
            self.ensure_type(T.struct_type(s.c_name))
        for ty in list(self.arrays) + list(self.tuples):
            self.ensure_type(ty)
        if self.structs or self.arrays or self.tuples:
            self.emit()

    def ensure_type(self, ty):
        if ty is None:
            return
        key = ty._key()
        if key in self.emitted_types:
            return
        if ty.kind == "pointer":
            if ty.elem is not None and ty.elem.kind in ("array", "tuple"):
                self.ensure_type(ty.elem)
            return
        if ty.kind == "list":
            return
        if key in self.emitting:
            return
        self.emitting.add(key)
        if ty.kind == "struct":
            s = self.struct_by_name.get(ty.name_)
            if s is not None:
                for f in s.fields:
                    self.ensure_type(f.ty)
                self.emit("struct %s {" % s.c_name)
                self.indent += 1
                if not s.fields:
                    self.emit("char _empty;")
                for f in s.fields:
                    self.emit("%s %s;" % (f.ty.c_name, f.name))
                self.indent -= 1
                self.emit("};")
                self.emit()
        elif ty.kind == "array":
            self.ensure_type(ty.elem)
            self.emit("typedef struct { %s data[%d]; } %s;"
                      % (ty.elem.c_name, ty.size, ty.c_name))
        elif ty.kind == "tuple":
            for elem in ty.elems:
                self.ensure_type(elem)
            self.emit("typedef struct {")
            self.indent += 1
            for i, elem in enumerate(ty.elems):
                self.emit("%s f%d;" % (elem.c_name, i))
            self.indent -= 1
            self.emit("} %s;" % ty.c_name)
        self.emitting.discard(key)
        self.emitted_types.add(key)

    def emit_type(self, ty):
        self.ensure_type(ty)

    # -- globals and constants -------------------------------------------
    def emit_globals(self):
        for name, g in self.globals.items():
            if g.is_const and g.values and self.is_static_init(g.values[0]):
                self.emit("static const %s %s = %s;"
                          % (g.ty.c_name, name, self.const_expr(g.values[0])))
            else:
                self.emit("static %s %s;" % (g.ty.c_name, name))
        if self.globals:
            self.emit()

    def emit_namespace_constants(self):
        emitted = False
        for ns in self.program.namespaces:
            for g in ns.constants:
                if len(g.names) != 1 or len(g.values) != 1:
                    continue
                name = "%s_%s" % (ns.name, g.names[0])
                if self.is_static_init(g.values[0]):
                    self.emit("static const %s %s = %s;"
                              % (g.ty.c_name, name, self.const_expr(g.values[0])))
                else:
                    self.emit("static %s %s;" % (g.ty.c_name, name))
                    self.deferred.append(("const", name, g))
                emitted = True
        if emitted:
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

    def emit_externs(self):
        if not self.externs:
            return
        external = [fn for fn in self.externs if not getattr(fn, "from_btl", False)]
        if not external:
            return
        self.emit("/* -- extern declarations ---------------------------------------------- */")
        for fn in external:
            self.emit("%s;" % self.signature(fn))
        self.emit()

    def emit_prototypes(self):
        for fn in self.all_functions():
            if fn.extern or fn.type_params:
                continue
            self.emit("%s;" % self.signature(fn))
        self.emit()

    def signature(self, fn):
        params = ", ".join("%s %s" % (p.ty.c_name, p.name) for p in fn.params)
        ret = "void" if fn.ret is None else fn.ret.c_name
        return "%s %s(%s)" % (ret, fn.c_name or fn.name, params)

    # -- comparator helpers ----------------------------------------------
    def emit_helpers(self):
        if not self.comparators:
            return
        self.emit("/* -- generated helpers ------------------------------------------------ */")
        for mangle, ty in self.comparators.items():
            name = "bt_cmp_%s" % mangle
            self.emit("static int %s(const void *pa, const void *pb) {" % name)
            self.indent += 1
            if ty == T.S:
                self.emit("const char *a = *(const char * const *)pa;")
                self.emit("const char *b = *(const char * const *)pb;")
                self.emit("return strcmp(a ? a : \"\", b ? b : \"\");")
            elif ty.kind in ("int", "uint", "float", "char", "bool"):
                self.emit("%s a = *(%s const *)pa;" % (ty.c_name, ty.c_name))
                self.emit("%s b = *(%s const *)pb;" % (ty.c_name, ty.c_name))
                self.emit("return (a > b) - (a < b);")
            else:
                self.emit("return memcmp(pa, pb, sizeof(%s));" % ty.c_name)
            self.indent -= 1
            self.emit("}")
        self.emit()

    def comparator_for(self, ty):
        if ty is None:
            ty = T.I
        self.comparators[ty.mangle] = ty
        return "bt_cmp_%s" % ty.mangle

    # -- functions -------------------------------------------------------
    def gen_fn(self, fn):
        self.indent = 0
        self.current_fn = fn
        params = ", ".join("%s %s" % (p.ty.c_name, p.name) for p in fn.params)
        ret = "void" if fn.ret is None else fn.ret.c_name
        self.emit("%s %s(%s) {" % (ret, fn.c_name or fn.name, params))
        self.indent += 1
        for s in fn.body.stmts:
            self.stmt(s)
        if fn.ret is not None and not _ends_with_return(fn.body.stmts):
            self.emit("return %s;  /* control reached the end */" % fn.ret.zero)
        if fn.ret is None and not fn.body.stmts:
            self.emit(";")
        self.indent -= 1
        self.emit("}")
        self.current_fn = None

    def emit_init(self):
        self.emit("static void bt_init(void) {")
        self.indent += 1
        if not self.deferred and not any(g.values for g in self.globals.values()):
            self.emit("(void)0;")
        for name, g in self.globals.items():
            if not g.values:
                continue
            value = g.values[0]
            if g.is_const and self.is_static_init(value):
                continue
            if self.is_static_init(value):
                self.emit("%s = %s;" % (name, self.const_expr(value)))
            else:
                self.emit("%s = %s;" % (name, self.expr(value)))
        for kind, name, g in self.deferred:
            if g.values:
                self.emit("%s = %s;" % (name, self.expr(g.values[0])))
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
        method = getattr(self, "stmt_" + type(node).__name__, None)
        if method is None:
            raise RuntimeError("unhandled statement %s" % type(node).__name__)
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
        if getattr(node, "unpack_from", None) is not None:
            call = node.unpack_from
            tuple_ty = call.ty
            text = self.expr(call)
            tmp = self.fresh("bt_unpack")
            self.emit("%s %s = %s;" % (tuple_ty.c_name, tmp, text))
            for i, name in enumerate(node.names):
                ty = node.tys[i] if i < len(node.tys) else T.I
                field = "%s.f%d" % (tmp, i)
                if ty != tuple_ty.elems[i]:
                    field = "((%s)%s)" % (ty.c_name, field)
                self.emit("%s %s = %s;" % (ty.c_name, name, field))
            return
        for i, name in enumerate(node.names):
            ty = node.tys[i] if i < len(node.tys) else (node.ty or T.I)
            value = node.values[i] if i < len(node.values) else None
            if value is None:
                self.emit("%s %s = %s;" % (ty.c_name, name, ty.zero))
            else:
                self.emit("%s %s = %s;" % (ty.c_name, name, self.expr(value)))

    def stmt_Assign(self, node):
        if getattr(node, "unpack_from", None) is not None:
            call = node.unpack_from
            tuple_ty = call.ty
            text = self.expr(call)
            tmp = self.fresh("bt_unpack")
            self.emit("%s %s = %s;" % (tuple_ty.c_name, tmp, text))
            for i, target in enumerate(node.targets):
                self.emit("%s = %s.f%d;" % (self.gen_lvalue(target), tmp, i))
            return
        if len(node.ops) == 1 and node.ops[0] == "=" and len(node.targets) > 1:
            temps = []
            for value in node.values:
                tmp = self.fresh("bt_swap")
                self.emit("%s %s = %s;" % (value.ty.c_name, tmp, self.expr(value)))
                temps.append(tmp)
            for target, tmp in zip(node.targets, temps):
                left = self.gen_lvalue(target)
                self.emit("%s = %s;" % (left, tmp))
            return
        for target, op, value in zip(node.targets, node.ops, node.values):
            left = self.gen_lvalue(target)
            right = self.expr(value)
            if op == "=":
                self.emit("%s = %s;" % (left, right))
            elif op == "**":
                if target.ty.is_int:
                    self.emit("%s = bt_ipow(%s, %s);" % (left, left, right))
                else:
                    self.emit("%s = bt_fpow(%s, %s);" % (left, left, right))
            elif op in ("/=", "%=") and target.ty.is_int:
                tmp = self.fresh("bt_rhs")
                self.emit("%s %s = %s;" % (target.ty.c_name, tmp, right))
                self.emit("bt_div_check((int64_t)%s);" % tmp)
                self.emit("%s %s %s;" % (left, op[0], tmp))
            else:
                self.emit("%s %s %s;" % (left, op, right))

    def stmt_ExprStmt(self, node):
        text = self.expr(node.expr)
        self.emit("%s;" % text)

    def stmt_If(self, node):
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
        for i, (cond, body) in enumerate(rendered):
            self.emit(("if (%s) {" if i == 0 else "} else if (%s) {") % cond)
            self.indent += 1
            if not body.stmts:
                self.emit(";")
            for s in body.stmts:
                self.stmt(s)
            self.indent -= 1
        if node.otherwise is not None:
            self.emit("} else {")
            self.indent += 1
            if not node.otherwise.stmts:
                self.emit(";")
            for s in node.otherwise.stmts:
                self.stmt(s)
            self.indent -= 1
        self.emit("}")

    def enter_loop(self, node):
        self.loop_counter += 1
        info = {
            "node": node,
            "break": "bt_lblk%d_break" % self.loop_counter,
            "next": "bt_lblk%d_next" % self.loop_counter,
        }
        self.loop_stack.append(info)
        return info

    def exit_loop(self):
        self.loop_stack.pop()

    def find_loop(self, label):
        for info in reversed(self.loop_stack):
            if info["node"].label == label:
                return info
        return None

    def stmt_While(self, node):
        info = self.enter_loop(node)
        self.emit("{")
        self.indent += 1
        self.emit("while (%s) {" % self.expr(node.cond))
        self.indent += 1
        if not node.body.stmts:
            self.emit(";")
        for s in node.body.stmts:
            self.stmt(s)
        self.emit("%s: ;" % info["next"])
        self.indent -= 1
        self.emit("}")
        self.emit("%s: ;" % info["break"])
        self.indent -= 1
        self.emit("}")
        self.exit_loop()

    def stmt_ForRange(self, node):
        info = self.enter_loop(node)
        ty = node.var_ty.c_name
        name = node.var
        self.emit("{")
        self.indent += 1
        lo = self.fresh("bt_lo")
        hi = self.fresh("bt_hi")
        step = self.fresh("bt_step")
        self.emit("%s %s = %s;" % (ty, lo, self.expr(node.start)))
        self.emit("%s %s = %s;" % (ty, hi, self.expr(node.end)))
        if node.step is not None:
            self.emit("int64_t %s = (int64_t)(%s);" % (step, self.expr(node.step)))
        else:
            self.emit("int64_t %s = 1;" % step)
        self.emit("%s %s = %s;" % (ty, name, lo))
        comp = "<=" if node.inclusive else "<"
        comp_down = ">=" if node.inclusive else ">"
        cond = ("(%s > 0 ? (%s %s %s) : (%s %s %s))"
                % (step, name, comp, hi, name, comp_down, hi))
        self.emit("while (%s) {" % cond)
        self.indent += 1
        if not node.body.stmts:
            self.emit(";")
        for s in node.body.stmts:
            self.stmt(s)
        self.emit("%s: ;" % info["next"])
        self.emit("%s += %s;" % (name, step))
        self.indent -= 1
        self.emit("}")
        self.emit("%s: ;" % info["break"])
        self.indent -= 1
        self.emit("}")
        self.exit_loop()

    def stmt_ForEach(self, node):
        info = self.enter_loop(node)
        iter_ty = node.iterable.ty
        self.emit("{")
        self.indent += 1
        source = self.fresh("bt_iter")
        elem = iter_ty.element_type()
        if iter_ty.kind == "list":
            self.emit("BtList *%s = %s;" % (source, self.expr(node.iterable)))
        elif iter_ty.kind == "array":
            self.emit("%s %s = %s;" % (iter_ty.c_name, source, self.expr(node.iterable)))
        elif iter_ty.kind == "str":
            self.emit("const char *%s = %s;" % (source, self.expr(node.iterable)))
        idx_name = node.index_var or self.fresh("bt_i")
        if iter_ty.kind == "str":
            self.emit("int64_t %s = 0;" % idx_name)
            self.emit("while (%s[%s]) {" % (source, idx_name))
        else:
            limit = "bt_list_len(%s)" % source if iter_ty.kind == "list" else str(iter_ty.size)
            self.emit("for (int64_t %s = 0; %s < %s; %s++) {"
                      % (idx_name, idx_name, limit, idx_name))
        self.indent += 1
        if iter_ty.kind == "list":
            self.emit("%s %s = *(%s *)bt_list_get(%s, %s, %d);"
                      % (elem.c_name, node.value_var, elem.c_name, source, idx_name, node.line))
        elif iter_ty.kind == "array":
            self.emit("%s %s = %s.data[%s];" % (elem.c_name, node.value_var, source, idx_name))
        else:
            self.emit("char %s = %s[%s];" % (node.value_var, source, idx_name))
        if not node.body.stmts:
            self.emit(";")
        for s in node.body.stmts:
            self.stmt(s)
        self.emit("%s: ;" % info["next"])
        if iter_ty.kind == "str":
            self.emit("%s++;" % idx_name)
        self.indent -= 1
        self.emit("}")
        self.emit("%s: ;" % info["break"])
        self.indent -= 1
        self.emit("}")
        self.exit_loop()

    def stmt_Loop(self, node):
        info = self.enter_loop(node)
        self.emit("{")
        self.indent += 1
        self.emit("for (;;) {")
        self.indent += 1
        if not node.body.stmts:
            self.emit(";")
        for s in node.body.stmts:
            self.stmt(s)
        self.emit("%s: ;" % info["next"])
        self.indent -= 1
        self.emit("}")
        self.emit("%s: ;" % info["break"])
        self.indent -= 1
        self.emit("}")
        self.exit_loop()

    def stmt_Break(self, node):
        if node.label is None:
            info = self.loop_stack[-1]
        else:
            info = self.find_loop(node.label)
        self.emit("goto %s;" % info["break"])

    def stmt_Continue(self, node):
        if node.label is None:
            info = self.loop_stack[-1]
        else:
            info = self.find_loop(node.label)
        self.emit("goto %s;" % info["next"])

    def stmt_Return(self, node):
        fn = self.current_fn
        if not node.values:
            self.emit("return;")
            return
        if len(node.values) == 1:
            value = node.values[0]
            text = self.expr(value)
            if fn.ret is not None and value.ty != fn.ret:
                text = "((%s)%s)" % (fn.ret.c_name, text)
            self.emit("return %s;" % text)
            return
        rets = fn.rets if fn is not None else []
        if fn is not None and fn.ret is not None and fn.ret.kind == "tuple":
            parts = []
            for i, value in enumerate(node.values):
                text = self.expr(value)
                if i < len(rets) and value.ty != rets[i]:
                    text = "((%s)%s)" % (rets[i].c_name, text)
                parts.append(".f%d = %s" % (i, text))
            self.emit("return (%s){ %s };" % (fn.ret.c_name, ", ".join(parts)))
        else:
            # Fallback for a malformed return: emit the first value.
            self.emit("return %s;" % self.expr(node.values[0]))

    def stmt_Match(self, node):
        subject = self.fresh("bt_match")
        self.emit("%s %s = %s;" % (node.subject.ty.c_name, subject, self.expr(node.subject)))
        first = True
        has_else = False
        for arm in node.arms:
            if arm.patterns is None:
                cond = None
                has_else = True
            else:
                parts = [self.pattern_condition(p, subject) for p in arm.patterns]
                cond = " || ".join(parts)
            if cond is None:
                self.emit(("} else {" if not first else "if (1) {"))
            else:
                self.emit(("} else if (%s) {" if not first else "if (%s) {") % cond)
            first = False
            self.indent += 1
            if not arm.body.stmts:
                self.emit(";")
            for s in arm.body.stmts:
                self.stmt(s)
            self.indent -= 1
        if not first:
            self.emit("}")
        if not has_else:
            self.emit("/* match had no else arm */")

    def pattern_condition(self, pat, subject):
        if isinstance(pat, RangePattern):
            lo = self.expr(pat.lo)
            hi = self.expr(pat.hi)
            op = "<=" if pat.inclusive else "<"
            return "((%s) >= (%s) && (%s) %s (%s))" % (subject, lo, subject, op, hi)
        text = self.expr(pat)
        if pat.ty == T.S:
            return "(bt_str_cmp(%s, %s) == 0)" % (subject, text)
        return "((%s) == (%s))" % (subject, text)

    # -- lvalues ---------------------------------------------------------
    def gen_lvalue(self, node):
        if isinstance(node, Name):
            return node.name
        if isinstance(node, Member):
            base = self.expr(node.obj)
            if getattr(node, "auto_deref", False):
                return "((%s)->%s)" % (base, node.name)
            return "((%s).%s)" % (base, node.name)
        if isinstance(node, Index):
            obj_ty = node.obj.ty
            obj = self.expr(node.obj)
            idx = self.expr(node.index)
            if obj_ty.kind == "list":
                return "(*((%s *)bt_list_get(%s, %s, %d)))" % (
                    obj_ty.elem.c_name, obj, idx, node.line)
            if obj_ty.kind == "array":
                return "((%s).data[%s])" % (obj, idx)
            if obj_ty.kind == "pointer":
                self.emit("bt_line = %d;" % node.line)
                self.emit("bt_null_check(%s, %d);" % (obj, node.line))
                return "((%s)[%s])" % (obj, idx)
            return "((%s)[%s])" % (obj, idx)
        if isinstance(node, Deref):
            operand = self.expr(node.operand)
            self.emit("bt_line = %d;" % node.line)
            self.emit("bt_null_check(%s, %d);" % (operand, node.line))
            return "(*%s)" % operand
        raise RuntimeError("not an lvalue: %s" % type(node).__name__)

    # -- expressions -----------------------------------------------------
    def expr(self, node):
        text = self.gen_expr(node)
        target = getattr(node, "coerce_to", None)
        if target is not None and target != node.ty:
            return "((%s)(%s))" % (target.c_name, text)
        return text

    def render_to(self, node):
        saved = self.lines
        self.lines = []
        text = self.expr(node)
        captured = self.lines
        self.lines = saved
        return text, captured

    def gen_expr(self, node):
        method = getattr(self, "gen_" + type(node).__name__, None)
        if method is None:
            raise RuntimeError("unhandled expression %s" % type(node).__name__)
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
        if getattr(node, "std_constant", None):
            key = node.std_constant
            return _MATH_CONSTANTS.get(key, "0")
        if getattr(node, "ns_constant", None):
            ns, _, member = node.ns_constant.partition(".")
            return "%s_%s" % (ns, member)
        return node.name

    def gen_Unary(self, node):
        operand = self.expr(node.operand)
        if node.op == "not":
            return "(!%s)" % operand
        if node.op == "~":
            return "(~%s)" % operand
        return "(%s%s)" % (node.op, operand)

    def gen_AddrOf(self, node):
        return "(&%s)" % self.gen_lvalue(node.operand)

    def gen_Deref(self, node):
        return self.gen_lvalue(node)

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
        if op == "@":
            return self.gen_matmul(node)
        if self.is_array_like(node.left.ty) or self.is_array_like(node.right.ty):
            return self.gen_array_binary(node)
        left_ty = node.left.ty
        if op == "+" and left_ty == T.S:
            return "bt_str_cat(%s, %s)" % (self.expr(node.left), self.expr(node.right))
        if left_ty == T.S and op in ("==", "!=", "<", "<=", ">", ">="):
            return "bt_str_cmp(%s, %s) %s 0" % (self.expr(node.left),
                                                self.expr(node.right),
                                                _CMP_OP[op])
        if op in ("/", "%") and node.ty.is_int:
            return self.gen_division(node, op)
        return "(%s %s %s)" % (self.expr(node.left), op, self.expr(node.right))

    @staticmethod
    def is_array_like(ty):
        return ty.kind in ("array", "list")

    def gen_division(self, node, op):
        left = self.fresh()
        right = self.fresh()
        self.emit("%s %s = %s;" % (node.ty.c_name, left, self.expr(node.left)))
        self.emit("%s %s = %s;" % (node.ty.c_name, right, self.expr(node.right)))
        self.emit("bt_line = %d;" % node.line)
        self.emit("bt_div_check((int64_t)%s);" % right)
        return "(%s %s %s)" % (left, op, right)

    def gen_array_binary(self, node):
        ty = node.ty
        if ty.kind != "array":
            # list arithmetic is not emitted; fall back to an element-wise loop
            return "0"
        out = self.fresh("bt_arr")
        self.emit("%s %s;" % (ty.c_name, out))
        left = node.left.ty.kind == "array"
        right = node.right.ty.kind == "array"
        ltext = self.expr(node.left) if left else self.expr(node.left)
        rtext = self.expr(node.right) if right else self.expr(node.right)
        if left and right:
            self.emit_array_assign(ty, out, ltext, rtext, node.op)
        elif left:
            self.emit_array_scalar(ty, out, ltext, rtext, node.op, node.right.ty,
                                   scalar_on_right=True)
        else:
            self.emit_array_scalar(ty, out, rtext, ltext, node.op, node.left.ty,
                                   scalar_on_right=False)
        return out

    def emit_array_assign(self, ty, out, left, right, op):
        if ty.kind != "array":
            return
        idx = self.fresh("bt_i")
        self.emit("for (int64_t %s = 0; %s < %d; %s++) {"
                  % (idx, idx, ty.size, idx))
        self.indent += 1
        if ty.elem.kind == "array":
            self.emit_array_assign(ty.elem, "%s.data[%s]" % (out, idx),
                                   "%s.data[%s]" % (left, idx),
                                   "%s.data[%s]" % (right, idx), op)
        else:
            self.emit("%s.data[%s] = %s.data[%s] %s %s.data[%s];"
                      % (out, idx, left, idx, op, right, idx))
        self.indent -= 1
        self.emit("}")

    def emit_array_scalar(self, ty, out, array, scalar, op, scalar_ty,
                          scalar_on_right):
        if ty.kind != "array":
            return
        idx = self.fresh("bt_i")
        self.emit("for (int64_t %s = 0; %s < %d; %s++) {"
                  % (idx, idx, ty.size, idx))
        self.indent += 1
        if ty.elem.kind == "array":
            self.emit_array_scalar(ty.elem, "%s.data[%s]" % (out, idx),
                                   "%s.data[%s]" % (array, idx), scalar, op,
                                   scalar_ty, scalar_on_right)
        else:
            expr = ("(%s.data[%s] %s %s)" if scalar_on_right
                    else "(%s %s %s.data[%s])")
            if scalar_on_right:
                self.emit("%s.data[%s] = %s;" % (out, idx, expr % (array, idx, op, scalar)))
            else:
                self.emit("%s.data[%s] = %s;" % (out, idx, expr % (scalar, op, array, idx)))
        self.indent -= 1
        self.emit("}")

    def gen_matmul(self, node):
        result = node.matrix_ty
        rows = result.size
        cols = result.elem.size
        inner = node.left.ty.elem.size
        elem = result.elem.elem
        out = self.fresh("bt_mat")
        left = self.expr(node.left)
        right = self.expr(node.right)
        self.emit("%s %s;" % (result.c_name, out))
        i = self.fresh("bt_i")
        j = self.fresh("bt_j")
        k = self.fresh("bt_k")
        self.emit("for (int64_t %s = 0; %s < %d; %s++) {" % (i, i, rows, i))
        self.indent += 1
        self.emit("for (int64_t %s = 0; %s < %d; %s++) {" % (j, j, cols, j))
        self.indent += 1
        self.emit("%s.data[%s].data[%s] = 0;" % (out, i, j))
        self.emit("for (int64_t %s = 0; %s < %d; %s++) {" % (k, k, inner, k))
        self.indent += 1
        self.emit("%s.data[%s].data[%s] += %s.data[%s].data[%s] * %s.data[%s].data[%s];"
                  % (out, i, j, left, i, k, right, k, j))
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")
        return out

    def gen_Member(self, node):
        if getattr(node, "ns_constant", None):
            ns, _, member = node.ns_constant.partition(".")
            return "%s_%s" % (ns, member)
        if getattr(node, "std_constant", None):
            return _MATH_CONSTANTS.get(node.std_constant, "0")
        return self.gen_lvalue(node)

    def gen_Index(self, node):
        return self.gen_lvalue(node)

    def gen_Slice(self, node):
        ty = node.obj.ty
        obj = self.expr(node.obj)
        start = self.expr(node.start) if node.start is not None else "0"
        if node.end is not None:
            end = self.expr(node.end)
            if node.inclusive:
                end = "((%s) + 1)" % end
        else:
            if ty.kind == "str":
                end = "(int64_t)strlen(%s)" % obj
            elif ty.kind == "array":
                end = str(ty.size)
            else:
                end = "bt_list_len(%s)" % obj
        if ty.kind == "str":
            return "bt_str_slice(%s, %s, %s, %d)" % (obj, start, end, node.line)
        if ty.kind == "array":
            obj = self.array_to_list_text(node.obj, obj)
        return "bt_list_slice(%s, %s, %s, %d)" % (obj, start, end, node.line)

    def gen_BraceLit(self, node):
        if node.kind == "struct":
            ty = node.ty
            parts = []
            for name, value in getattr(node, "resolved_entries", []):
                text = self.expr(value)
                field_ty = value.ty
                parts.append(".%s = %s" % (name, text))
            return "((%s){ %s })" % (ty.c_name, ", ".join(parts))
        if node.kind == "array":
            ty = node.ty
            vals = ", ".join(self.expr(value) for _, value in node.entries)
            return "((%s){ .data = { %s } })" % (ty.c_name, vals)
        if node.kind == "tuple":
            ty = node.ty
            vals = ", ".join(".f%d = %s" % (i, self.expr(value))
                             for i, (_, value) in enumerate(node.entries))
            return "((%s){ %s })" % (ty.c_name, vals)
        # growable list
        ty = node.ty
        out = self.fresh("bt_list")
        elem = ty.elem
        self.emit("BtList *%s = bt_list_new(sizeof(%s), %d);"
                  % (out, elem.c_name, len(node.entries)))
        for _, value in node.entries:
            tmp = self.fresh("bt_v")
            self.emit("%s %s = %s;" % (elem.c_name, tmp, self.expr(value)))
            self.emit("%s = bt_list_push(%s, &%s, sizeof(%s));"
                      % (out, out, tmp, tmp))
        return out

    def gen_Call(self, node):
        if getattr(node, "builtin", None):
            return self.gen_builtin(node)
        if getattr(node, "std", None):
            return self.gen_std_call(node)
        if getattr(node, "target", None) is None:
            return "0"
        args = ", ".join(self.hoist(a) for a in node.args)
        return "%s(%s)" % (node.target.c_name, args)

    def gen_MethodCall(self, node):
        if getattr(node, "namespace_call", None) is not None:
            return self.gen_Call(node.namespace_call)
        if getattr(node, "method_builtin", None) is not None:
            return self.gen_Call(node.method_builtin)
        obj = self.expr(node.obj)
        args = [self.hoist(a) for a in node.args]
        if node.obj.ty.kind == "file":
            if node.name == "write":
                return "bt_file_write(%s, %s, %d)" % (obj, args[0], node.line)
            if node.name == "line":
                return self.wrap_tuple("bt_file_line_result",
                                       "bt_file_line(%s, %d)" % (obj, node.line),
                                       node.ty)
            if node.name == "read":
                return "bt_file_read(%s, %s, %d)" % (obj, args[0], node.line)
            if node.name == "close":
                return "bt_file_close(%s, %d)" % (obj, node.line)
            if node.name == "seek":
                return "bt_file_seek(%s, %s, %d)" % (obj, args[0], node.line)
            if node.name == "tell":
                return "bt_file_tell(%s, %d)" % (obj, node.line)
        if node.obj.ty.kind == "list" and node.name == "clone":
            return "bt_list_clone(%s)" % obj
        return "0"

    def hoist(self, node):
        text = self.expr(node)
        if not _has_side_effect(node):
            return text
        temp = self.fresh("bt_arg")
        self.emit("%s %s = %s;" % (node.ty.c_name, temp, text))
        return temp

    # -- standard library -------------------------------------------------
    def gen_std_call(self, node):
        std = node.std
        ns = std[0]
        member = std[1]
        if ns == "math":
            args = ", ".join(self.hoist(a) for a in node.args)
            return "%s(%s)" % (_MATH_C[member], args)
        if ns == "str":
            args = [self.hoist(a) for a in node.args]
            if member == "lower":
                return "bt_str_lower(%s)" % args[0]
            if member == "upper":
                return "bt_str_upper(%s)" % args[0]
            if member == "trim":
                return "bt_str_trim(%s)" % args[0]
            if member == "has":
                return "bt_str_has(%s, %s)" % (args[0], args[1])
            if member == "starts":
                return "bt_str_starts(%s, %s)" % (args[0], args[1])
            if member == "ends":
                return "bt_str_ends(%s, %s)" % (args[0], args[1])
            if member == "split":
                return "bt_str_split(%s, %s)" % (args[0], args[1])
            if member == "join":
                parts = self.ensure_list(node.args[0])
                return "bt_str_join(%s, %s)" % (parts, args[1])
        if ns == "list":
            elem = std[2]
            cmp = self.comparator_for(elem)
            if member == "sort":
                if node.args[0].ty.kind == "array":
                    arr = self.expr(node.args[0])
                    return "qsort(%s.data, %d, sizeof(%s), %s)" % (
                        arr, node.args[0].ty.size, elem.c_name, cmp)
                lst = self.expr(node.args[0])
                return "bt_list_sort(%s, %s)" % (lst, cmp)
            if member == "reverse":
                if node.args[0].ty.kind == "array":
                    return self.array_reverse(node.args[0])
                return "bt_list_reverse(%s)" % self.expr(node.args[0])
            if member == "indexof":
                lst = self.ensure_list(node.args[0])
                value = self.hoist(node.args[1])
                tmp = self.fresh("bt_v")
                self.emit("%s %s = %s;" % (elem.c_name, tmp, value))
                return self.wrap_tuple("bt_indexof_result",
                                       "bt_list_indexof(%s, &%s, sizeof(%s), %s)"
                                       % (lst, tmp, tmp, cmp), node.ty)
        if ns == "rand":
            if member == "int":
                return "bt_rand_int(%s, %s)" % (self.hoist(node.args[0]),
                                                self.hoist(node.args[1]))
            if member == "float":
                return "bt_rand_float()"
            if member == "seed":
                return "bt_rand_seed(%s)" % self.hoist(node.args[0])
        if ns == "time":
            return "bt_time_now()" if member == "now" else "bt_time_tick()"
        if ns == "fs":
            args = [self.hoist(a) for a in node.args]
            if member == "exists":
                return "bt_fs_exists(%s)" % args[0]
            if member == "mkdir":
                return "bt_fs_mkdir(%s)" % args[0]
            if member == "remove":
                return "bt_fs_remove(%s)" % args[0]
            if member == "err":
                return "bt_fs_err()"
            if member == "list":
                return self.wrap_tuple("bt_str_list_result",
                                       "bt_fs_list(%s)" % args[0], node.ty)
        if ns == "task":
            if member == "spawn":
                spawned = node.args[0]
                text = self.expr(spawned)
                if spawned.ty == T.VOID:
                    return "bt_task_new(0)"
                return "bt_task_new((int64_t)(%s))" % text
            if member == "wait":
                return "bt_task_wait(%s)" % self.hoist(node.args[0])
            if member == "join":
                return "bt_task_join(%s)" % self.hoist(node.args[0])
            if member == "stop":
                return "bt_task_stop(%s)" % self.hoist(node.args[0])
        return "0"

    def ensure_list(self, node):
        if node.ty.kind == "list":
            return self.expr(node)
        if node.ty.kind == "array":
            text = self.expr(node)
            out = self.fresh("bt_list")
            elem = node.ty.elem
            self.emit("BtList *%s = bt_list_new(sizeof(%s), %d);"
                      % (out, elem.c_name, node.ty.size))
            for i in range(node.ty.size):
                tmp = self.fresh("bt_v")
                self.emit("%s %s = %s.data[%d];" % (elem.c_name, tmp, text, i))
                self.emit("%s = bt_list_push(%s, &%s, sizeof(%s));"
                          % (out, out, tmp, tmp))
            return out
        return self.expr(node)

    def array_to_list_text(self, node, text):
        elem = node.ty.elem
        out = self.fresh("bt_list")
        self.emit("BtList *%s = bt_list_new(sizeof(%s), %d);"
                  % (out, elem.c_name, node.ty.size))
        for i in range(node.ty.size):
            tmp = self.fresh("bt_v")
            self.emit("%s %s = %s.data[%d];" % (elem.c_name, tmp, text, i))
            self.emit("%s = bt_list_push(%s, &%s, sizeof(%s));"
                      % (out, out, tmp, tmp))
        return out

    def array_reverse(self, node):
        text = self.expr(node)
        elem = node.ty.elem
        tmp = self.fresh("bt_v")
        i = self.fresh("bt_i")
        j = self.fresh("bt_j")
        self.emit("{")
        self.indent += 1
        self.emit("for (int64_t %s = 0, %s = %d - 1; %s < %s; %s++, %s--) {"
                  % (i, j, node.ty.size, i, j, i, j))
        self.indent += 1
        self.emit("%s %s = %s.data[%s];" % (elem.c_name, tmp, text, i))
        self.emit("%s.data[%s] = %s.data[%s];" % (text, i, text, j))
        self.emit("%s.data[%s] = %s;" % (text, j, tmp))
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")
        return "((void)0)"

    def wrap_tuple(self, runtime_ty, call, tuple_ty):
        tmp = self.fresh("bt_res")
        self.emit("%s %s = %s;" % (runtime_ty, tmp, call))
        return "((%s){ .f0 = %s.f0, .f1 = %s.f1 })" % (tuple_ty.c_name, tmp, tmp)

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
        if kind == "to":
            return self.gen_to(node)
        if kind == "try":
            if node.name == "tryi":
                return self.wrap_tuple("bt_tryi_result",
                                       "bt_tryi(%s)" % self.hoist(node.args[0]), node.ty)
            return self.wrap_tuple("bt_tryf_result",
                                   "bt_tryf(%s)" % self.hoist(node.args[0]), node.ty)
        if kind == "len":
            arg = node.args[0]
            text = self.expr(arg)
            if arg.ty.kind == "list":
                return "bt_list_len(%s)" % text
            if arg.ty.kind == "array":
                return str(arg.ty.size)
            return "((int64_t)strlen(%s))" % text
        if kind == "push":
            target = node.args[0]
            elem = target.ty.elem
            tmp = self.fresh("bt_v")
            self.emit("%s %s = %s;" % (elem.c_name, tmp, self.expr(node.args[1])))
            lval = self.gen_lvalue(target)
            self.emit("%s = bt_list_push(%s, &%s, sizeof(%s));"
                      % (lval, lval, tmp, tmp))
            return "((void)0)"
        if kind == "pop":
            arg = node.args[0]
            elem = arg.ty.elem
            return "(*((%s *)bt_list_pop(%s, %d)))" % (
                elem.c_name, self.expr(arg), node.line)
        if kind == "clone":
            if node.args[0].ty.kind == "list":
                return "bt_list_clone(%s)" % self.expr(node.args[0])
            return self.expr(node.args[0])
        if kind == "isnull":
            return "((%s) == NULL)" % self.expr(node.args[0])
        if kind == "cstr":
            return "bt_cstr(%s)" % self.expr(node.args[0])
        if kind == "alloc":
            return "bt_alloc((int64_t)(%s), sizeof(%s), %d)" % (
                self.expr(node.args[1]), node.alloc_ty.c_name, node.line)
        if kind == "free":
            return "free(%s)" % self.expr(node.args[0])
        if kind == "readfile":
            return self.wrap_tuple("bt_readfile_result",
                                   "bt_readfile(%s)" % self.hoist(node.args[0]), node.ty)
        if kind == "writefile":
            return "bt_writefile(%s, %s)" % (self.hoist(node.args[0]),
                                             self.hoist(node.args[1]))
        if kind == "fopen":
            return self.wrap_tuple("bt_fopen_result",
                                   "bt_fopen(%s, %s)" % (self.hoist(node.args[0]),
                                                         self.hoist(node.args[1])), node.ty)
        return "0"

    def gen_print(self, node, newline):
        if not node.args:
            return "putchar('\\n')" if newline else "((void)0)"
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
        return 'printf("%s"%s)' % (fmt, (", " + ", ".join(args)) if args else "")

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
            if src_ty.is_unsigned_int:
                return "bt_tos_u((uint64_t)(%s))" % text
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
        return True
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
