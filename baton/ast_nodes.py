"""The abstract syntax tree produced by the parser."""


class Node:
    line = 0
    col = 1
    span = 0
    ty = None  # filled in by the checker


# -- expressions ---------------------------------------------------------
class Expr(Node):
    pass


class IntLit(Expr):
    def __init__(self, value, line, col, span, text=""):
        self.value = value
        self.text = text
        self.line, self.col, self.span = line, col, span


class FloatLit(Expr):
    def __init__(self, value, line, col, span, text=""):
        self.value = value
        self.text = text
        self.line, self.col, self.span = line, col, span


class StrLit(Expr):
    def __init__(self, value, line, col, span):
        self.value = value
        self.line, self.col, self.span = line, col, span


class CharLit(Expr):
    def __init__(self, value, line, col, span):
        self.value = value
        self.line, self.col, self.span = line, col, span


class BoolLit(Expr):
    def __init__(self, value, line, col, span):
        self.value = value
        self.line, self.col, self.span = line, col, span


class Name(Expr):
    def __init__(self, name, line, col, span):
        self.name = name
        self.line, self.col, self.span = line, col, span


class Unary(Expr):
    def __init__(self, op, operand, line, col, span):
        self.op = op
        self.operand = operand
        self.line, self.col, self.span = line, col, span


class AddrOf(Expr):
    def __init__(self, operand, line, col, span):
        self.operand = operand
        self.line, self.col, self.span = line, col, span


class Deref(Expr):
    def __init__(self, operand, line, col, span):
        self.operand = operand
        self.line, self.col, self.span = line, col, span


class Binary(Expr):
    def __init__(self, op, left, right, line, col, span):
        self.op = op
        self.left = left
        self.right = right
        self.line, self.col, self.span = line, col, span


class Cast(Expr):
    def __init__(self, operand, target, line, col, span):
        self.operand = operand
        self.target = target  # a Ty
        self.line, self.col, self.span = line, col, span


class Call(Expr):
    def __init__(self, name, args, line, col, span, name_span=1, type_args=None):
        self.name = name
        self.args = args
        self.name_span = name_span
        self.type_args = type_args or []
        self.line, self.col, self.span = line, col, span


class Member(Expr):
    """``obj.field``.  The checker turns this into a field or method access."""

    def __init__(self, obj, name, line, col, span):
        self.obj = obj
        self.name = name
        self.line, self.col, self.span = line, col, span


class MethodCall(Expr):
    def __init__(self, obj, name, args, line, col, span):
        self.obj = obj
        self.name = name
        self.args = args
        self.line, self.col, self.span = line, col, span


class Index(Expr):
    def __init__(self, obj, index, line, col, span):
        self.obj = obj
        self.index = index
        self.line, self.col, self.span = line, col, span


class Slice(Expr):
    def __init__(self, obj, start, end, inclusive, line, col, span):
        self.obj = obj
        self.start = start
        self.end = end
        self.inclusive = inclusive
        self.line, self.col, self.span = line, col, span


class BraceLit(Expr):
    def __init__(self, entries, line, col, span):
        self.entries = entries  # [(name or None, Expr)]
        self.line, self.col, self.span = line, col, span


# -- statements ----------------------------------------------------------
class Stmt(Node):
    pass


class VarDecl(Stmt):
    def __init__(self, ty, names, values, is_const, line, col, span,
                 inferred=False, name_spans=None, init_spans=None, tys=None):
        self.ty = ty
        self.tys = tys or [ty] * len(names)
        self.names = names
        self.values = values
        self.is_const = is_const
        self.inferred = inferred
        self.name_spans = name_spans or [1] * len(names)
        self.init_spans = init_spans or [0] * len(names)
        self.line, self.col, self.span = line, col, span


class Assign(Stmt):
    def __init__(self, targets, ops, values, line, col, span):
        self.targets = targets
        self.ops = ops
        self.values = values
        self.line, self.col, self.span = line, col, span


class ExprStmt(Stmt):
    def __init__(self, expr, line, col, span):
        self.expr = expr
        self.line, self.col, self.span = line, col, span


class Block(Stmt):
    def __init__(self, stmts, line, col, span):
        self.stmts = stmts
        self.line, self.col, self.span = line, col, span


class If(Stmt):
    def __init__(self, branches, otherwise, line, col, span):
        self.branches = branches      # [(cond, Block)]
        self.otherwise = otherwise    # Block or None
        self.line, self.col, self.span = line, col, span


class While(Stmt):
    def __init__(self, cond, body, label, line, col, span):
        self.cond = cond
        self.body = body
        self.label = label
        self.line, self.col, self.span = line, col, span
        self.loop_id = None


class ForRange(Stmt):
    def __init__(self, var, start, end, inclusive, step, body, label, line, col, span):
        self.var = var
        self.start = start
        self.end = end
        self.inclusive = inclusive
        self.step = step
        self.body = body
        self.label = label
        self.line, self.col, self.span = line, col, span
        self.loop_id = None
        self.var_ty = None


class ForEach(Stmt):
    def __init__(self, index_var, value_var, iterable, body, label, line, col, span):
        self.index_var = index_var   # str or None
        self.value_var = value_var
        self.iterable = iterable
        self.body = body
        self.label = label
        self.line, self.col, self.span = line, col, span
        self.loop_id = None
        self.value_ty = None


class Loop(Stmt):
    def __init__(self, body, label, line, col, span):
        self.body = body
        self.label = label
        self.line, self.col, self.span = line, col, span
        self.loop_id = None


class Break(Stmt):
    def __init__(self, label, line, col, span):
        self.label = label
        self.line, self.col, self.span = line, col, span


class Continue(Stmt):
    def __init__(self, label, line, col, span):
        self.label = label
        self.line, self.col, self.span = line, col, span


class Return(Stmt):
    def __init__(self, value, line, col, span, values=None):
        self.value = value
        self.values = values if values is not None else ([value] if value is not None else [])
        self.line, self.col, self.span = line, col, span


class MatchArm:
    def __init__(self, patterns, body, line, col):
        self.patterns = patterns  # [Expr] or None for else
        self.body = body
        self.line, self.col = line, col


class Match(Stmt):
    def __init__(self, subject, arms, line, col, span):
        self.subject = subject
        self.arms = arms
        self.line, self.col, self.span = line, col, span


class RangePattern:
    def __init__(self, lo, hi, inclusive, line, col):
        self.lo = lo
        self.hi = hi
        self.inclusive = inclusive
        self.line, self.col = line, col


# -- top level -----------------------------------------------------------
class Param:
    def __init__(self, ty, name, line, col):
        self.ty = ty
        self.name = name
        self.line, self.col = line, col


class TypeParam:
    def __init__(self, name, constraint, line, col):
        self.name = name
        self.constraint = constraint
        self.line, self.col = line, col


class FnDecl(Stmt):
    def __init__(self, name, params, ret, body, line, col, span, name_span=1,
                 type_params=None, rets=None, extern=False, c_name=None):
        self.name = name
        self.params = params
        self.ret = ret  # Ty or None for void
        self.rets = list(rets) if rets is not None else ([] if ret is None else [ret])
        self.body = body
        self.name_span = name_span
        self.type_params = type_params or []
        self.extern = extern
        self.c_name = c_name
        self.line, self.col, self.span = line, col, span
        self.generic_key = None
        self.parent_generic = None


class NamespaceDecl(Stmt):
    def __init__(self, name, params, ret, functions, constants, line, col, span,
                 rets=None):
        self.name = name
        self.params = params       # shared parameters, in declaration order
        self.ret = ret             # Ty, or None when the namespace uses `det`
        self.rets = list(rets) if rets is not None else ([] if ret is None else [ret])
        self.functions = functions # [FnDecl]
        self.constants = constants # [VarDecl]
        self.line, self.col, self.span = line, col, span


class FieldDecl:
    def __init__(self, ty, name, line, col):
        self.ty = ty
        self.name = name
        self.line, self.col = line, col


class StructDecl(Stmt):
    def __init__(self, name, type_params, fields, line, col, span, c_name=None):
        self.name = name
        self.type_params = type_params or []
        self.fields = fields
        self.line, self.col, self.span = line, col, span
        self.c_name = c_name or name
        self.generic_key = None
        self.parent_generic = None


class Expose(Stmt):
    def __init__(self, names, line, col, span):
        self.names = names
        self.line, self.col, self.span = line, col, span


class ModuleImport(Stmt):
    def __init__(self, alias, path, line, col, span,
                 package=None, version=None, entry=None):
        self.alias = alias
        self.path = path
        self.package = package
        self.version = version
        self.entry = entry
        self.line, self.col, self.span = line, col, span
        self.resolved = None


class Program:
    def __init__(self, globals_, functions, modules=None, namespaces=None,
                 structs=None, exposes=None, imports=None):
        self.globals = globals_      # [VarDecl]
        self.functions = functions   # [FnDecl]
        self.modules = modules or [] # legacy path list
        self.namespaces = namespaces or []
        self.structs = structs or []
        self.exposes = exposes or []
        self.imports = imports or []
        # filled in by the checker / loader
        self.struct_types = []
        self.tuple_types = []
        self.array_types = []
        self.externs = []
        self.btl_includes = []
        self.module_aliases = {}
