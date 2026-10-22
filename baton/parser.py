"""Tokens -> AST (specification sections 2 through 10)."""

from . import types as T
from .ast_nodes import (
    Assign, Binary, Block, BoolLit, Break, Call, Cast, CharLit, Continue, ExprStmt,
    FloatLit, FnDecl, ForRange, If, IntLit, Loop, Name, Param, Program, Return,
    StrLit, Unary, VarDecl, While,
)
from .diagnostics import CompileError
from .lexer import lex

# Features the parser recognises but this build does not compile yet.
_UNIMPLEMENTED = {
    "struct": "structs (spec 11)",
    "match": "match (spec 10)",
    "ns": "namespaces (spec 9)",
    "expose": "expose (spec 19)",
    "extern": "extern fn (spec 8)",
}

_ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "%=", "**=")


def unimpl(what, line, col):
    return CompileError("%s is not implemented in this build yet" % what, line, col)


class Parser:
    def __init__(self, tokens, source, filename):
        self.toks = tokens
        self.src = source
        self.filename = filename
        self.pos = 0

    # -- token access ----------------------------------------------------
    def peek(self, ahead=0):
        j = self.pos + ahead
        if j >= len(self.toks):
            return self.toks[-1]
        return self.toks[j]

    def at(self, kind=None, text=None):
        t = self.peek()
        if kind and t.kind != kind:
            return False
        if text is not None and t.text != text:
            return False
        return True

    def next(self):
        t = self.peek()
        if t.kind != "EOF":
            self.pos += 1
        return t

    def accept_op(self, text):
        if self.at("OP", text):
            return self.next()
        return None

    def accept_kw(self, text):
        if self.at("KW", text):
            return self.next()
        return None

    def expect_op(self, text, what=None):
        t = self.accept_op(text)
        if t is None:
            got = self.peek()
            raise CompileError("expected '%s'%s, found %s" % (
                text, (" " + what) if what else "", self._describe(got)),
                got.line, got.col)
        return t

    def expect_kw(self, text, what=None):
        t = self.accept_kw(text)
        if t is None:
            got = self.peek()
            raise CompileError("expected '%s'%s, found %s" % (
                text, (" " + what) if what else "", self._describe(got)),
                got.line, got.col)
        return t

    def expect_ident(self, what="a name"):
        t = self.peek()
        if t.kind != "IDENT":
            raise CompileError("expected %s, found %s" % (what, self._describe(t)), t.line, t.col)
        return self.next()

    @staticmethod
    def _describe(tok):
        if tok.kind == "EOF":
            return "end of file"
        if tok.kind == "NL":
            return "end of line"
        return "'%s'" % tok.text

    def skip_newlines(self):
        while self.at("NL") or self.at("OP", ";"):
            self.next()

    def skip_newlines_after_block(self):
        """A `}` closes a statement; the newline that follows it is optional."""
        self.skip_newlines()

    # -- top level -------------------------------------------------------
    def parse(self):
        globals_ = []
        functions = []
        modules = []
        self.skip_newlines()
        while not self.at("EOF"):
            t = self.peek()
            if t.kind == "KW":
                if t.text == "fn":
                    functions.append(self.parse_fn())
                elif t.text == "mod":
                    modules.append(self.parse_mod())
                elif t.text in _UNIMPLEMENTED:
                    raise unimpl(_UNIMPLEMENTED[t.text], t.line, t.col)
                elif t.text in ("local", "const"):
                    globals_.append(self.parse_var_decl())
                else:
                    raise CompileError("'%s' is not allowed at the top level" % t.text, t.line, t.col)
            elif t.kind == "IDENT" and T.is_type_name(t.text) and self.peek(1).kind == "KW" \
                    and self.peek(1).text in ("local", "const"):
                globals_.append(self.parse_var_decl())
            else:
                raise CompileError("expected a top-level declaration, found %s"
                                   % self._describe(t), t.line, t.col)
            self.skip_newlines()
        return Program(globals_, functions, modules)

    def parse_mod(self):
        t = self.expect_kw("mod")
        t2 = self.peek()
        if t2.kind == "KW" and t2.text == "get-from":
            raise CompileError("modules are not implemented in this build yet (spec 19)", t.line, t.col)
        if t2.kind == "IDENT":
            self.next()
            t3 = self.expect_kw("get-from", "after the module alias")
        else:
            t3 = self.expect_kw("get-from", "after 'mod'")
        p = self.peek()
        if p.kind != "STR":
            raise CompileError("expected a quoted module path, found %s" % self._describe(p), p.line, p.col)
        self.next()
        raise CompileError("modules are not implemented in this build yet (spec 19)", t.line, t.col)

    # -- functions -------------------------------------------------------
    def parse_fn(self):
        start = self.expect_kw("fn")
        name = self.expect_ident("a function name")
        if self.at("OP", "<"):
            raise unimpl("generics (spec 21)", self.peek().line, self.peek().col)
        params = self.parse_params()
        ret = None
        if self.accept_op("->"):
            first = self.parse_type()
            if self.at("OP", ","):
                raise unimpl("multiple return values (spec 8)", self.peek().line, self.peek().col)
            ret = first
        body = self.parse_block()
        end = self.toks[self.pos - 1]
        return FnDecl(name.text, params, ret, body, start.line, start.col,
                      max(1, end.off - start.off + len(end.text)), len(name.text))

    def parse_params(self):
        self.expect_op("(")
        params = []
        if not self.at("OP", ")"):
            while True:
                ty = self.parse_type()
                name = self.expect_ident("a parameter name")
                params.append(Param(ty, name.text, name.line, name.col))
                if not self.accept_op(","):
                    break
        self.expect_op(")", "to close the parameter list")
        return params

    def parse_type(self):
        t = self.peek()
        if t.kind == "OP" and t.text == "*":
            raise unimpl("pointers (spec 20)", t.line, t.col)
        if t.kind == "OP" and t.text == "[":
            raise unimpl("arrays and lists (spec 12)", t.line, t.col)
        if t.kind != "IDENT":
            raise CompileError("expected a type, found %s" % self._describe(t), t.line, t.col)
        if self.peek(1).kind == "OP" and self.peek(1).text == "<":
            raise unimpl("generics (spec 21)", t.line, t.col)
        if self.peek(1).kind == "OP" and self.peek(1).text == "[":
            raise unimpl("arrays and lists (spec 12)", t.line, t.col)
        self.next()
        try:
            return T.parse(t.text)
        except KeyError:
            raise CompileError("unknown type '%s'%s" % (t.text, self._type_hint(t.text)), t.line, t.col)

    @staticmethod
    def _type_hint(text):
        if text and text[0].isupper():
            return " — structs are not implemented in this build yet (spec 11)"
        return ""

    # -- statements ------------------------------------------------------
    def parse_block(self):
        start = self.expect_op("{", "to open a block")
        stmts = []
        self.skip_newlines()
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise CompileError("unterminated block", start.line, start.col)
            stmts.append(self.parse_stmt())
            self.skip_newlines()
        end = self.expect_op("}")
        return Block(stmts, start.line, start.col, max(1, end.off - start.off + 1))

    def parse_stmt(self):
        t = self.peek()

        # a label before a loop: `outer: while ...`
        if t.kind == "IDENT" and self.peek(1).kind == "OP" and self.peek(1).text == ":":
            label = self.next()
            self.next()  # the colon
            nxt = self.peek()
            if nxt.kind == "KW" and nxt.text in ("while", "for", "loop"):
                return self.parse_loop(label.text)
            raise CompileError("a label must go directly before a loop", label.line, label.col)

        if t.kind == "KW":
            kw = t.text
            if kw in _UNIMPLEMENTED:
                raise unimpl(_UNIMPLEMENTED[kw], t.line, t.col)
            if kw in ("while", "for", "loop"):
                return self.parse_loop(None)
            if kw in ("local", "const"):
                return self.parse_var_decl()
            if kw == "if":
                return self.parse_if()
            if kw == "return":
                return self.parse_return()
            if kw == "break":
                return self.parse_break()
            if kw == "continue":
                return self.parse_continue()
            if kw == "fn":
                raise CompileError("functions must be declared at the top level", t.line, t.col)
            raise CompileError("unexpected '%s'" % kw, t.line, t.col)

        if t.kind == "OP" and t.text == "{":
            return self.parse_block()

        # `<type> local x`, or a plain declaration with no prefix
        if t.kind == "IDENT" and T.is_type_name(t.text) and self.peek(1).kind == "KW" \
                and self.peek(1).text in ("local", "const"):
            return self.parse_var_decl()

        if t.kind == "IDENT" and self.peek(1).kind == "OP" and self.peek(1).text == "[":
            raise unimpl("arrays and lists (spec 12)", t.line, t.col)

        return self.parse_assign_or_call()

    def parse_var_decl(self):
        start = self.peek()
        ty = None
        if self.at("IDENT") and T.is_type_name(self.peek().text):
            ty = self.parse_type()
        kw = self.peek()
        if kw.kind != "KW" or kw.text not in ("local", "const"):
            raise CompileError("expected 'local' or 'const' in a declaration", kw.line, kw.col)
        self.next()
        is_const = kw.text == "const"

        names = []
        name_spans = []
        while True:
            name = self.expect_ident("a variable name")
            names.append(name.text)
            name_spans.append(len(name.text))
            if not self.accept_op(","):
                break

        values = []
        init_spans = [0] * len(names)
        if self.accept_op("="):
            values = self.parse_expr_list()
            self._check_values_implementable(values)

        end = self.toks[self.pos - 1]
        span = max(1, end.off - start.off + len(end.text))
        return VarDecl(ty, names, values, is_const, start.line, start.col, span,
                       inferred=(ty is None), name_spans=name_spans, init_spans=init_spans)

    @staticmethod
    def _check_values_implementable(values):
        return

    def parse_assign_or_call(self):
        start = self.peek()
        targets = [self.parse_expr()]
        while self.accept_op(","):
            targets.append(self.parse_expr())
        ops = []
        values = []
        if self.at("OP") and self.peek().text in _ASSIGN_OPS:
            ops.append(self.next().text)
            values = self.parse_expr_list()
        if ops:
            if len(ops) != 1 or len(targets) != len(values):
                bad = targets[len(values)] if len(targets) > len(values) else None
                line = bad.line if bad and len(ops) == 1 else start.line
                col = bad.col if bad and len(ops) == 1 else start.col
                raise CompileError("assignment needs the same number of names and values", line, col)
            for tgt in targets:
                if not isinstance(tgt, Name):
                    raise CompileError("can only assign to a variable", tgt.line, tgt.col)
            end = self.toks[self.pos - 1]
            return Assign(targets, ops, values, start.line, start.col,
                          max(1, end.off - start.off + len(end.text)))
        if len(targets) != 1 or not isinstance(targets[0], Call):
            node = targets[0]
            raise CompileError("only a call can stand alone as a statement", node.line, node.col)
        end = self.toks[self.pos - 1]
        return ExprStmt(targets[0], start.line, start.col,
                        max(1, end.off - start.off + len(end.text)))

    def parse_if(self):
        start = self.expect_kw("if")
        branches = []
        cond = self.parse_expr()
        body = self.parse_block()
        branches.append((cond, body))
        otherwise = None
        while True:
            self.skip_newlines()
            if self.accept_kw("elf"):
                cond = self.parse_expr()
                branches.append((cond, self.parse_block()))
                continue
            if self.accept_kw("else"):
                otherwise = self.parse_block()
            break
        end = self.toks[self.pos - 1]
        return If(branches, otherwise, start.line, start.col,
                  max(1, end.off - start.off + len(end.text)))

    def parse_loop(self, label):
        start = self.peek()
        if start.is_kw("while"):
            self.next()
            cond = self.parse_expr()
            body = self.parse_block()
            end = self.toks[self.pos - 1]
            return While(cond, body, label, start.line, start.col,
                         max(1, end.off - start.off + len(end.text)))
        if start.is_kw("loop"):
            self.next()
            body = self.parse_block()
            end = self.toks[self.pos - 1]
            return Loop(body, label, start.line, start.col,
                        max(1, end.off - start.off + len(end.text)))
        if start.is_kw("for"):
            self.next()
            var = self.expect_ident("a loop variable")
            self.expect_kw("in", "in a for loop")
            first = self.parse_expr()
            inclusive = False
            if self.accept_op("..="):
                inclusive = True
            elif self.accept_op(".."):
                inclusive = False
            else:
                bad = self.peek()
                raise CompileError(
                    "for needs a range like '0..10'; iterating a list is not "
                    "implemented in this build yet (spec 12)", bad.line, bad.col)
            second = self.parse_expr()
            step = None
            if self.accept_kw("by"):
                step = self.parse_expr()
            body = self.parse_block()
            end = self.toks[self.pos - 1]
            return ForRange(var.text, first, second, inclusive, step, body, label,
                            start.line, start.col, max(1, end.off - start.off + len(end.text)))
        raise CompileError("expected a loop", start.line, start.col)

    def parse_return(self):
        start = self.expect_kw("return")
        value = None
        if not (self.at("NL") or self.at("EOF") or self.at("OP", "}") or self.at("OP", ";")):
            value = self.parse_expr()
            if self.accept_op("->"):
                raise unimpl("the return determiner (spec 8)", start.line, start.col)
            if self.at("OP", ","):
                raise unimpl("multiple return values (spec 8)", self.peek().line, self.peek().col)
        end = self.toks[self.pos - 1]
        return Return(value, start.line, start.col, max(1, end.off - start.off + len(end.text)))

    def parse_break(self):
        start = self.expect_kw("break")
        label = None
        if self.at("IDENT"):
            label = self.next().text
        end = self.toks[self.pos - 1] if label else start
        return Break(label, start.line, start.col, max(1, end.off - start.off + len(end.text)))

    def parse_continue(self):
        start = self.expect_kw("continue")
        label = None
        if self.at("IDENT"):
            label = self.next().text
        end = self.toks[self.pos - 1] if label else start
        return Continue(label, start.line, start.col, max(1, end.off - start.off + len(end.text)))

    # -- expressions -----------------------------------------------------
    def parse_expr_list(self):
        values = [self.parse_expr()]
        while self.at("OP", ","):
            self.next()
            values.append(self.parse_expr())
        return values

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at("KW", "or"):
            op = self.next()
            right = self.parse_and()
            left = Binary("or", left, right, op.line, op.col, 3)
        return left

    def parse_and(self):
        left = self.parse_cmp()
        while self.at("KW", "and"):
            op = self.next()
            right = self.parse_cmp()
            left = Binary("and", left, right, op.line, op.col, 3)
        return left

    def parse_cmp(self):
        left = self.parse_bitor()
        while self.at("OP") and self.peek().text in ("<", "<=", ">", ">=", "==", "!="):
            op = self.next()
            right = self.parse_bitor()
            left = Binary(op.text, left, right, op.line, op.col, len(op.text))
        return left

    def parse_bitor(self):
        left = self.parse_bitxor()
        while self.at("OP", "|"):
            op = self.next()
            left = Binary("|", left, self.parse_bitxor(), op.line, op.col, 1)
        return left

    def parse_bitxor(self):
        left = self.parse_bitand()
        while self.at("OP", "^"):
            op = self.next()
            left = Binary("^", left, self.parse_bitand(), op.line, op.col, 1)
        return left

    def parse_bitand(self):
        left = self.parse_shift()
        while self.at("OP", "&"):
            op = self.next()
            left = Binary("&", left, self.parse_shift(), op.line, op.col, 1)
        return left

    def parse_shift(self):
        left = self.parse_add()
        while self.at("OP") and self.peek().text in ("<<", ">>"):
            op = self.next()
            left = Binary(op.text, left, self.parse_add(), op.line, op.col, 2)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.at("OP") and self.peek().text in ("+", "-"):
            op = self.next()
            left = Binary(op.text, left, self.parse_mul(), op.line, op.col, 1)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.at("OP") and self.peek().text in ("*", "/", "%"):
            op = self.next()
            left = Binary(op.text, left, self.parse_unary(), op.line, op.col, 1)
        return left

    def parse_unary(self):
        t = self.peek()
        if t.kind == "OP" and t.text in ("-", "+", "~", "*", "&"):
            if t.text in ("*", "&"):
                raise unimpl("pointers (spec 20)", t.line, t.col)
            if t.text == "+":
                raise CompileError("baton has no unary '+'", t.line, t.col)
            self.next()
            operand = self.parse_unary()
            node = Unary(t.text, operand, t.line, t.col, 1)
        elif t.kind == "KW" and t.text == "not":
            self.next()
            operand = self.parse_unary()
            node = Unary("not", operand, t.line, t.col, 3)
        else:
            node = self.parse_power()

        while self.at("KW", "as"):
            op = self.next()
            target = self.parse_type()
            node = Cast(node, target, op.line, op.col, 2)
        return node

    def parse_power(self):
        base = self.parse_postfix()
        if self.at("OP", "**"):
            op = self.next()
            rhs = self.parse_unary()
            return Binary("**", base, rhs, op.line, op.col, 2)
        return base

    def parse_postfix(self):
        node = self.parse_primary()
        while True:
            t = self.peek()
            if t.kind == "OP" and t.text == "(":
                if not isinstance(node, Name):
                    raise CompileError("only a named function can be called", t.line, t.col)
                args = self.parse_args()
                end = self.toks[self.pos - 1]
                span = max(1, end.off - node.off + len(end.text))
                node = Call(node.name, args, node.line, node.col, span, node.span)
            elif t.kind == "OP" and t.text in (".", "["):
                raise unimpl("fields, methods and indexing (specs 11-14)",
                             t.line, t.col)
            else:
                break
        return node

    def parse_args(self):
        self.expect_op("(")
        args = []
        if not self.at("OP", ")"):
            while True:
                args.append(self.parse_expr())
                if not self.accept_op(","):
                    break
        self.expect_op(")", "to close the call")
        return args

    def parse_primary(self):
        t = self.peek()
        if t.kind == "INT":
            self.next()
            return IntLit(t.value, t.line, t.col, len(t.text), t.text)
        if t.kind == "FLOAT":
            self.next()
            return FloatLit(t.value, t.line, t.col, len(t.text), t.text)
        if t.kind == "STR":
            self.next()
            return StrLit(t.value, t.line, t.col, 1)
        if t.kind == "CHAR":
            self.next()
            return CharLit(t.value, t.line, t.col, 1)
        if t.kind == "KW" and t.text in ("true", "false"):
            self.next()
            return BoolLit(t.text == "true", t.line, t.col, len(t.text))
        if t.kind == "OP" and t.text == "(":
            self.next()
            expr = self.parse_expr()
            self.expect_op(")", "to close the group")
            return expr
        if t.kind == "OP" and t.text == "{":
            raise unimpl("struct and list literals (specs 11-12)", t.line, t.col)
        if t.kind == "IDENT":
            self.next()
            node = Name(t.text, t.line, t.col, len(t.text))
            node.off = t.off
            return node
        raise CompileError("expected an expression, found %s" % self._describe(t), t.line, t.col)


def parse(tokens, source, filename):
    return Parser(tokens, source, filename).parse()


def parse_source(source, filename="<source>"):
    return parse(lex(source, filename), source, filename)
