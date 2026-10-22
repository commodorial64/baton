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
    def __init__(self, name, args, line, col, span, name_span=1):
        self.name = name
        self.args = args
        self.name_span = name_span
        self.line, self.col, self.span = line, col, span


# -- statements ----------------------------------------------------------
class Stmt(Node):
    pass


class VarDecl(Stmt):
    def __init__(self, ty, names, values, is_const, line, col, span,
                 inferred=False, name_spans=None, init_spans=None):
        self.ty = ty
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
    def __init__(self, value, line, col, span):
        self.value = value
        self.line, self.col, self.span = line, col, span


# -- top level -----------------------------------------------------------
class Param:
    def __init__(self, ty, name, line, col):
        self.ty = ty
        self.name = name
        self.line, self.col = line, col


class FnDecl(Stmt):
    def __init__(self, name, params, ret, body, line, col, span, name_span=1):
        self.name = name
        self.params = params
        self.ret = ret  # Ty or None for void
        self.body = body
        self.name_span = name_span
        self.line, self.col, self.span = line, col, span
        self.c_name = None


class Program:
    def __init__(self, globals_, functions, modules):
        self.globals = globals_      # [VarDecl]
        self.functions = functions   # [FnDecl]
        self.modules = modules       # [str] paths, not implemented yet
