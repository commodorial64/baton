"""Tokens -> AST (specification sections 2 through 10)."""

import re

from . import types as T
from .ast_nodes import (
    AddrOf, Assign, Binary, Block, BoolLit, BraceLit, Break, Call, Cast, CharLit,
    Continue, Deref, ExprStmt, FloatLit, FnDecl, ForEach, ForRange, If, Index,
    IntLit, Loop, Match, MatchArm, Member, MethodCall, ModuleImport, Name,
    NamespaceDecl, Param, Program, RangePattern, Return, Slice, StrLit, StructDecl,
    FieldDecl, TypeParam, Unary, VarDecl, While, Expose,
)
from .diagnostics import CompileError
from .lexer import lex

_ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "%=", "**=")


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

    def expect_int(self, what="an integer"):
        t = self.peek()
        if t.kind != "INT":
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
        namespaces = []
        structs = []
        exposes = []
        imports = []
        self.skip_newlines()
        while not self.at("EOF"):
            t = self.peek()
            if t.kind == "KW":
                if t.text == "fn":
                    functions.append(self.parse_fn())
                elif t.text == "ns":
                    namespaces.append(self.parse_ns())
                elif t.text == "struct":
                    structs.append(self.parse_struct())
                elif t.text == "expose":
                    exposes.append(self.parse_expose())
                elif t.text == "mod":
                    imports.append(self.parse_mod())
                elif t.text == "extern":
                    functions.append(self.parse_extern())
                elif t.text in ("local", "const"):
                    globals_.append(self.parse_var_decl())
                else:
                    raise CompileError("'%s' is not allowed at the top level" % t.text, t.line, t.col)
            elif self._at_type_start() and self._type_starts_decl():
                globals_.append(self.parse_var_decl())
            else:
                raise CompileError("expected a top-level declaration, found %s"
                                   % self._describe(t), t.line, t.col)
            self.skip_newlines()
        return Program(globals_, functions, modules, namespaces, structs, exposes, imports)

    def parse_mod(self):
        start = self.expect_kw("mod")
        alias = None
        if self.peek().kind == "IDENT":
            alias = self.next().text
        self.expect_kw("get-from", "after 'mod'")
        p = self.peek()
        if p.kind == "STR":
            self.next()
            end = self.toks[self.pos - 1]
            return ModuleImport(alias, p.text, start.line, start.col,
                                max(1, end.off - start.off + len(end.text)))
        if p.is_op("<"):
            return self.parse_package_mod(alias, start)
        raise CompileError("expected a quoted module path or <package>, found %s"
                           % self._describe(p), p.line, p.col)

    def parse_package_mod(self, alias, start):
        lt = self.expect_op("<")
        close = self.src.find(">", lt.off + 1)
        newline = self.src.find("\n", lt.off + 1)
        if close == -1 or (newline != -1 and newline < close):
            raise CompileError("unterminated package import; expected '>'",
                               lt.line, lt.col)
        target = self.src[lt.off + 1:close].strip()
        if not target:
            raise CompileError("empty package import", lt.line, lt.col)
        end = close + 1
        self._skip_tokens_to(end)

        # The version may sit outside the angle brackets: <sharpe>@0.2
        version = None
        pos = end
        while pos < len(self.src) and self.src[pos] in " \t":
            pos += 1
        if pos < len(self.src) and self.src[pos] == "@":
            begin = pos + 1
            pos = begin
            while pos < len(self.src):
                ch = self.src[pos]
                if ch.isspace() or ch == ";":
                    break
                if self.src.startswith("--", pos) or self.src.startswith("/-", pos):
                    break
                pos += 1
            version = self.src[begin:pos]
            if not version:
                raise CompileError("expected a version after '@'",
                                   self.toks[self.pos - 1].line,
                                   self.toks[self.pos - 1].col)
            end = pos
            self._skip_tokens_to(end)

        outside_version = version
        package, _, entry = target.partition("/")
        entry = entry.strip() or None
        if "@" in package:
            package, _, inline = package.partition("@")
            if version is not None and version != inline:
                raise CompileError("package version given twice", start.line, start.col)
            version = inline
        package = package.strip()

        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", package):
            raise CompileError("invalid package name '%s'" % package,
                               start.line, start.col)
        if version is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
            raise CompileError("invalid package version '%s'" % version,
                               start.line, start.col)
        if entry:
            parts = entry.replace("\\", "/").split("/")
            if entry.startswith("/") or ".." in parts:
                raise CompileError("invalid package entry '%s'" % entry,
                                   start.line, start.col)

        display = "<%s>" % target
        if outside_version is not None:
            display += "@" + outside_version
        return ModuleImport(alias, display, start.line, start.col,
                            max(1, end - start.off),
                            package=package, version=version, entry=entry)

    def _skip_tokens_to(self, offset):
        """Consume tokens that begin before `offset` (a raw source position)."""
        while self.pos < len(self.toks) and self.toks[self.pos].off < offset:
            self.next()

    def parse_expose(self):
        start = self.expect_kw("expose")
        names = [self.expect_ident("a name to expose").text]
        while self.accept_op(","):
            names.append(self.expect_ident("a name to expose").text)
        end = self.toks[self.pos - 1]
        return Expose(names, start.line, start.col,
                      max(1, end.off - start.off + len(end.text)))

    # -- type parameters -------------------------------------------------
    def parse_type_params(self):
        self.expect_op("<")
        params = []
        if not self.at_type_gt():
            while True:
                name = self.expect_ident("a type parameter")
                constraint = None
                if self.accept_op(":"):
                    c = self.expect_ident("a type constraint")
                    constraint = c.text
                    if constraint not in ("num", "ord"):
                        raise CompileError("unknown type constraint '%s' (use num or ord)"
                                           % constraint, c.line, c.col)
                params.append(TypeParam(name.text, constraint, name.line, name.col))
                if not self.accept_op(","):
                    break
        self.expect_type_gt("to close the type parameters")
        return params

    def at_type_gt(self):
        return self.at("OP", ">") or self.at("OP", ">>")

    def expect_type_gt(self, what=None):
        t = self.peek()
        if t.kind == "OP" and t.text == ">":
            return self.next()
        if t.kind == "OP" and t.text == ">>":
            # In a type, >> is two closes (spec 21).
            from .lexer import Token
            self.toks[self.pos] = Token("OP", ">", t.line, t.col, off=t.off + 1)
            return Token("OP", ">", t.line, t.col, off=t.off)
        raise CompileError("expected '>'%s, found %s" % (
            (" " + what) if what else "", self._describe(t)), t.line, t.col)

    # -- namespaces ------------------------------------------------------
    def parse_ns(self):
        start = self.expect_kw("ns")
        name = self.expect_ident("a namespace name")
        params = []
        if self.at("OP", "("):
            params = self.parse_params()
        ret = None
        rets = []
        determined = True
        if self.accept_op("->"):
            if self.accept_kw("det"):
                determined = True
            else:
                ty = self.parse_type()
                if self.at("OP", ","):
                    raise CompileError("namespace return types are single (spec 9)",
                                       self.peek().line, self.peek().col)
                ret = ty
                rets = [ty]
                determined = False
        self.expect_op("{", "to open the namespace")
        self.skip_newlines()

        functions = []
        constants = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise CompileError("unterminated namespace", start.line, start.col)
            t = self.peek()
            if t.kind == "KW" and t.text == "functions":
                self.next()
                self.expect_op("{", "to open the functions block")
                self.skip_newlines()
                while not self.at("OP", "}"):
                    if self.at("EOF"):
                        raise CompileError("unterminated functions block", t.line, t.col)
                    functions.append(self.parse_ns_fn(name.text, params, ret,
                                                      rets, determined))
                    self.skip_newlines()
                self.expect_op("}", "to close the functions block")
            elif t.kind == "KW" and t.text == "const":
                constants.append(self.parse_var_decl())
            elif t.kind == "IDENT" and T.is_type_name(t.text) and \
                    self.peek(1).kind == "KW" and self.peek(1).text == "const":
                constants.append(self.parse_var_decl())
            elif t.kind == "KW" and t.text == "local":
                raise CompileError("namespace members must be const", t.line, t.col)
            elif t.kind == "IDENT" and T.is_type_name(t.text) and \
                    self.peek(1).kind == "KW" and self.peek(1).text == "local":
                raise CompileError("namespace members must be const", t.line, t.col)
            else:
                raise CompileError("expected 'functions' or 'const' in namespace '%s', found %s"
                                   % (name.text, self._describe(t)), t.line, t.col)
            self.skip_newlines()

        end = self.expect_op("}", "to close the namespace")
        return NamespaceDecl(name.text, params, ret, functions, constants,
                             start.line, start.col,
                             max(1, end.off - start.off + 1), rets=rets)

    def parse_ns_fn(self, ns_name, shared, ns_ret, ns_rets, determined):
        start = self.expect_ident("a namespace function name")
        own = self.parse_params()
        ret = ns_ret
        rets = list(ns_rets)
        det = determined and ns_ret is None
        if self.accept_op("->"):
            if self.accept_kw("det"):
                ret = None
                rets = []
                det = True
            else:
                rets = [self.parse_type()]
                if self.at("OP", ","):
                    raise CompileError("namespace return types are single (spec 9)",
                                       self.peek().line, self.peek().col)
                ret = rets[0]
                det = False
        body = self.parse_block()
        end = self.toks[self.pos - 1]
        fn = FnDecl(start.text, list(shared) + own, ret, body,
                    start.line, start.col,
                    max(1, end.off - start.off + len(end.text)), len(start.text),
                    rets=rets)
        fn.namespace = ns_name
        fn.shared_count = len(shared)
        fn.det_return = det
        return fn

    # -- functions -------------------------------------------------------
    def parse_fn(self):
        start = self.expect_kw("fn")
        name = self.expect_ident("a function name")
        type_params = []
        if self.at("OP", "<"):
            type_params = self.parse_type_params()
        params = self.parse_params()
        rets = self.parse_return_types()
        body = self.parse_block()
        end = self.toks[self.pos - 1]
        return self.make_fn(name, params, rets, body, start,
                            max(1, end.off - start.off + len(end.text)),
                            type_params=type_params)

    def parse_extern(self):
        start = self.expect_kw("extern")
        self.expect_kw("fn")
        name = self.expect_ident("a function name")
        params = self.parse_params(allow_unnamed=True)
        rets = self.parse_return_types()
        end = self.toks[self.pos - 1]
        fn = self.make_fn(name, params, rets, None, start,
                          max(1, end.off - start.off + len(end.text)))
        fn.extern = True
        fn.name_span = len(name.text)
        return fn

    @staticmethod
    def make_fn(name, params, rets, body, start, span, type_params=None):
        ret = rets[0] if len(rets) == 1 else (T.tuple_type(rets) if rets else None)
        return FnDecl(name.text, params, ret, body, start.line, start.col, span,
                      len(name.text), type_params=type_params, rets=rets)

    def parse_return_types(self):
        rets = []
        if self.accept_op("->"):
            if self.accept_kw("det"):
                return rets
            rets.append(self.parse_type())
            while self.accept_op(","):
                rets.append(self.parse_type())
        return rets

    def parse_params(self, allow_unnamed=False):
        self.expect_op("(")
        params = []
        if not self.at("OP", ")"):
            while True:
                ty = self.parse_type()
                if self.peek().kind == "IDENT":
                    name = self.next()
                elif allow_unnamed:
                    name = None
                else:
                    raise CompileError("expected a parameter name, found %s"
                                       % self._describe(self.peek()),
                                       self.peek().line, self.peek().col)
                params.append(Param(ty, name.text if name else "arg%d" % len(params),
                                    name.line if name else ty_line(ty), name.col if name else 1))
                if not self.accept_op(","):
                    break
        self.expect_op(")", "to close the parameter list")
        return params

    # -- types -----------------------------------------------------------
    def _at_type_start(self):
        t = self.peek()
        return (t.kind == "IDENT" or (t.kind == "OP" and t.text in ("*", "[")))

    def _type_starts_decl(self):
        """Look ahead past a type to see whether a declaration follows."""
        saved = self.pos
        try:
            self.parse_type()
            t = self.peek()
            return t.kind == "KW" and t.text in ("local", "const")
        except CompileError:
            return False
        finally:
            self.pos = saved

    def parse_type(self):
        t = self.peek()
        if t.kind == "OP" and t.text == "*":
            self.next()
            return T.pointer_to(self.parse_type())
        if t.kind != "IDENT":
            raise CompileError("expected a type, found %s" % self._describe(t), t.line, t.col)
        self.next()
        if t.text == "File":
            base = T.FILE
        elif t.text == "Task":
            base = T.TASK
        else:
            try:
                base = T.parse(t.text)
            except KeyError:
                base = T.named(t.text)
        if self.at("OP", "<"):
            args = self.parse_type_args()
            base = T.struct_type(t.text, args)
        dims = []
        while self.at("OP", "["):
            self.next()
            if self.accept_op("]"):
                dims.append(None)
            else:
                n = self.expect_int("an array size")
                self.expect_op("]", "to close the array size")
                if n.value <= 0:
                    raise CompileError("an array size must be positive", n.line, n.col)
                dims.append(n.value)
        for dim in reversed(dims):
            base = T.list_of(base) if dim is None else T.array_of(base, dim)
        return base

    def parse_type_args(self):
        self.expect_op("<")
        args = []
        if not self.at_type_gt():
            while True:
                args.append(self.parse_type())
                if not self.accept_op(","):
                    break
        self.expect_type_gt("to close the type arguments")
        return args

    # -- structs ---------------------------------------------------------
    def parse_struct(self):
        start = self.expect_kw("struct")
        name = self.expect_ident("a struct name")
        type_params = []
        if self.at("OP", "<"):
            type_params = self.parse_type_params()
        self.expect_op("{", "to open the struct")
        self.skip_newlines()
        fields = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise CompileError("unterminated struct", start.line, start.col)
            ty = self.parse_type()
            field = self.expect_ident("a field name")
            fields.append(FieldDecl(ty, field.text, field.line, field.col))
            self.skip_newlines()
        end = self.expect_op("}", "to close the struct")
        return StructDecl(name.text, type_params, fields, start.line, start.col,
                          max(1, end.off - start.off + len(end.text)))

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
            if kw in ("while", "for", "loop"):
                return self.parse_loop(None)
            if kw in ("local", "const"):
                return self.parse_var_decl()
            if kw == "if":
                return self.parse_if()
            if kw == "match":
                return self.parse_match()
            if kw == "return":
                return self.parse_return()
            if kw == "break":
                return self.parse_break()
            if kw == "continue":
                return self.parse_continue()
            if kw == "fn":
                raise CompileError("functions must be declared at the top level", t.line, t.col)
            if kw in ("struct", "expose", "extern", "mod", "ns"):
                raise CompileError("'%s' is only allowed at the top level" % kw, t.line, t.col)
            raise CompileError("unexpected '%s'" % kw, t.line, t.col)

        if t.kind == "OP" and t.text == "{":
            return self.parse_block()

        # `<type> local x`, or a plain declaration with no prefix
        if self._at_type_start() and self._type_starts_decl():
            return self.parse_var_decl()

        return self.parse_assign_or_call()

    def parse_var_decl(self):
        start = self.peek()
        first_ty = None
        if not (self.peek().kind == "KW" and self.peek().text in ("local", "const")):
            first_ty = self.parse_type()
        kw = self.peek()
        if kw.kind != "KW" or kw.text not in ("local", "const"):
            raise CompileError("expected 'local' or 'const' in a declaration", kw.line, kw.col)
        self.next()
        is_const = kw.text == "const"

        entries = []
        while True:
            ty = first_ty
            # Each name after a comma may carry its own prefix, which is what
            # makes `i local n, b ok = tryi(...)` work.
            if entries and self._at_type_start() and self._type_before_name():
                ty = self.parse_type()
            name = self.expect_ident("a variable name")
            entries.append((ty, name))
            if not self.accept_op(","):
                break

        names = [n.text for _, n in entries]
        tys = [ty for ty, _ in entries]
        name_spans = [len(n) for n in names]
        values = []
        init_spans = [0] * len(names)
        if self.accept_op("="):
            values = self.parse_expr_list()

        end = self.toks[self.pos - 1]
        span = max(1, end.off - start.off + len(end.text))
        node = VarDecl(first_ty, names, values, is_const, start.line, start.col, span,
                       inferred=(all(t is None for t in tys)),
                       name_spans=name_spans, init_spans=init_spans, tys=tys)
        return node

    def _type_before_name(self):
        saved = self.pos
        try:
            self.parse_type()
            ok = self.peek().kind == "IDENT"
            return ok
        except CompileError:
            return False
        finally:
            self.pos = saved

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
            end = self.toks[self.pos - 1]
            return Assign(targets, ops, values, start.line, start.col,
                          max(1, end.off - start.off + len(end.text)))
        if len(targets) != 1 or not isinstance(targets[0], (Call, MethodCall)):
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

    def parse_match(self):
        start = self.expect_kw("match")
        subject = self.parse_expr()
        self.expect_op("{", "to open match")
        self.skip_newlines()
        arms = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise CompileError("unterminated match", start.line, start.col)
            arm_start = self.peek()
            patterns = None
            if self.accept_kw("else"):
                patterns = None
            else:
                patterns = [self.parse_pattern()]
                while self.accept_op(","):
                    patterns.append(self.parse_pattern())
            body = self.parse_block()
            arms.append(MatchArm(patterns, body, arm_start.line, arm_start.col))
            self.skip_newlines()
        end = self.expect_op("}", "to close match")
        return Match(subject, arms, start.line, start.col,
                     max(1, end.off - start.off + len(end.text)))

    def parse_pattern(self):
        start = self.peek()
        lo = self.parse_expr()
        if self.accept_op("..="):
            hi = self.parse_expr()
            return RangePattern(lo, hi, True, start.line, start.col)
        if self.accept_op(".."):
            hi = self.parse_expr()
            return RangePattern(lo, hi, False, start.line, start.col)
        return lo

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
            first = self.expect_ident("a loop variable")
            index_var = None
            value_var = first
            if self.accept_op(","):
                index_var = first.text
                value_var = self.expect_ident("a value variable")
            self.expect_kw("in", "in a for loop")
            first_expr = self.parse_expr()
            inclusive = False
            is_range = False
            if self.accept_op("..="):
                inclusive = True
                is_range = True
            elif self.accept_op(".."):
                is_range = False
                is_range = True
            if is_range:
                second = self.parse_expr()
                step = None
                if self.accept_kw("by"):
                    step = self.parse_expr()
                body = self.parse_block()
                end = self.toks[self.pos - 1]
                return ForRange(value_var.text, first_expr, second, inclusive, step,
                                body, label, start.line, start.col,
                                max(1, end.off - start.off + len(end.text)))
            body = self.parse_block()
            end = self.toks[self.pos - 1]
            return ForEach(index_var, value_var.text, first_expr, body, label,
                           start.line, start.col,
                           max(1, end.off - start.off + len(end.text)))
        raise CompileError("expected a loop", start.line, start.col)

    def parse_return(self):
        start = self.expect_kw("return")
        values = []
        if not (self.at("NL") or self.at("EOF") or self.at("OP", "}") or self.at("OP", ";")):
            values.append(self.parse_expr())
            while self.accept_op(","):
                values.append(self.parse_expr())
            if self.accept_op("->"):
                # The determiner is accepted and checked against the expression.
                ty = self.parse_type()
                if len(values) == 1:
                    values[0].declared_ret = ty
        end = self.toks[self.pos - 1]
        value = values[0] if len(values) == 1 else None
        return Return(value, start.line, start.col,
                      max(1, end.off - start.off + len(end.text)), values=values)

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
        left = self.parse_matmul()
        while self.at("OP") and self.peek().text in ("*", "/", "%"):
            op = self.next()
            left = Binary(op.text, left, self.parse_matmul(), op.line, op.col, 1)
        return left

    def parse_matmul(self):
        left = self.parse_unary()
        while self.at("OP", "@"):
            op = self.next()
            left = Binary("@", left, self.parse_unary(), op.line, op.col, 1)
        return left

    def parse_unary(self):
        t = self.peek()
        if t.kind == "OP" and t.text in ("-", "+", "~", "*", "&"):
            if t.text == "+":
                raise CompileError("baton has no unary '+'", t.line, t.col)
            self.next()
            operand = self.parse_unary()
            if t.text == "*":
                node = Deref(operand, t.line, t.col, 1)
            elif t.text == "&":
                node = AddrOf(operand, t.line, t.col, 1)
            else:
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
        start_tok = self.peek()
        start_off = start_tok.off
        node = self.parse_primary()
        while True:
            t = self.peek()
            if t.kind == "OP" and t.text == "<" and isinstance(node, Name) and \
                    self._looks_like_type_args():
                type_args = self.parse_type_args()
                self.expect_op("(", "after type arguments")
                args = self._parse_call_args_after_open()
                end = self.toks[self.pos - 1]
                node = Call(node.name, args, node.line, node.col,
                            max(1, end.off - start_off + len(end.text)), node.span,
                            type_args=type_args)
            elif t.kind == "OP" and t.text == "(":
                if not isinstance(node, Name):
                    raise CompileError("only a named function can be called", t.line, t.col)
                args = self.parse_args()
                end = self.toks[self.pos - 1]
                span = max(1, end.off - start_off + len(end.text))
                node = Call(node.name, args, node.line, node.col, span, node.span)
            elif t.kind == "OP" and t.text == ".":
                self.next()
                member = self.peek()
                if member.kind != "IDENT":
                    raise CompileError("expected a member after '.', found %s"
                                       % self._describe(member), member.line, member.col)
                self.next()
                if self.at("OP", "("):
                    args = self.parse_args()
                    end = self.toks[self.pos - 1]
                    node = MethodCall(node, member.text, args, node.line, node.col,
                                      max(1, end.off - start_off + len(end.text)))
                else:
                    node = Member(node, member.text, node.line, node.col,
                                  max(1, member.off + len(member.text) - start_off))
            elif t.kind == "OP" and t.text == "[":
                self.next()
                start = None
                if not self.at("OP", "..") and not self.at("OP", "..="):
                    start = self.parse_expr()
                if self.accept_op("..=") or self.accept_op(".."):
                    inclusive = self.toks[self.pos - 1].text == "..="
                    end_expr = self.parse_expr()
                    self.expect_op("]", "to close the slice")
                    end = self.toks[self.pos - 1]
                    node = Slice(node, start, end_expr, inclusive, node.line, node.col,
                                 max(1, end.off - start_off + len(end.text)))
                else:
                    self.expect_op("]", "to close the index")
                    end = self.toks[self.pos - 1]
                    node = Index(node, start, node.line, node.col,
                                 max(1, end.off - start_off + len(end.text)))
            else:
                break
        return node

    def _looks_like_type_args(self):
        saved = self.pos
        try:
            self.parse_type_args()
            return self.at("OP", "(")
        except CompileError:
            return False
        finally:
            self.pos = saved

    def parse_args(self):
        self.expect_op("(")
        return self._parse_call_args_after_open()

    def _parse_call_args_after_open(self):
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
            return self.parse_brace_lit()
        if t.kind == "IDENT":
            self.next()
            node = Name(t.text, t.line, t.col, len(t.text))
            node.off = t.off
            return node
        raise CompileError("expected an expression, found %s" % self._describe(t), t.line, t.col)

    def parse_brace_lit(self):
        start = self.expect_op("{")
        entries = []
        self.skip_newlines()
        if not self.at("OP", "}"):
            while True:
                if self.peek().kind == "IDENT" and self.peek(1).kind == "OP" and \
                        self.peek(1).text == "=":
                    name = self.next()
                    self.next()
                    entries.append((name.text, self.parse_expr()))
                else:
                    entries.append((None, self.parse_expr()))
                if not self.accept_op(","):
                    break
                self.skip_newlines()
        end = self.expect_op("}", "to close the literal")
        return BraceLit(entries, start.line, start.col,
                        max(1, end.off - start.off + len(end.text)))


def ty_line(ty):
    return 1


def parse(tokens, source, filename):
    return Parser(tokens, source, filename).parse()


def parse_source(source, filename="<source>"):
    return parse(lex(source, filename), source, filename)
