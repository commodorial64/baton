"""Source text -> tokens (specification section 2)."""

from .diagnostics import CompileError

KEYWORDS = {
    "local", "const", "fn", "ns", "functions", "struct",
    "if", "elf", "else", "while", "for", "in", "by", "loop", "break",
    "continue", "return", "as", "and", "or", "not", "true", "false", "det",
    "mod", "expose", "extern", "match",
}

# Longest first, so the scanner never splits a two-character operator.
OPERATORS = [
    "..=", "**=", "<<=", ">>=",
    "..", "**", "<<", ">>", "<=", ">=", "==", "!=", "+=", "-=", "*=", "/=",
    "%=", "->",
    "&", "|", "^", "~", "+", "-", "*", "/", "%", "<", ">", "=", "!", "@",
    "(", ")", "{", "}", "[", "]", ",", ".", ":", ";",
]

# A newline after one of these continues the expression on the next line.
_CONTINUATION = {
    "+", "-", "*", "/", "%", "**", "=", "+=", "-=", "*=", "/=", "%=", "**=",
    "<<", ">>", "&", "|", "^", "<", ">", "<=", ">=", "==", "!=", "and", "or",
    "not", "as", ",", "->", "..", "..=", "by", "in", "@",
}

_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0",
}


class Token:
    __slots__ = ("kind", "text", "line", "col", "value", "off")

    def __init__(self, kind, text, line, col, value=None, off=0):
        self.kind = kind      # IDENT INT FLOAT STR CHAR KW OP NL EOF
        self.text = text
        self.line = line
        self.col = col
        self.value = value    # decoded literal value
        self.off = off        # character offset in the source

    def is_op(self, text):
        return self.kind == "OP" and self.text == text

    def is_kw(self, text):
        return self.kind == "KW" and self.text == text

    def __repr__(self):
        return "Token(%s,%r,%d:%d)" % (self.kind, self.text, self.line, self.col)


class Lexer:
    def __init__(self, source, filename="<source>"):
        self.src = source
        self.filename = filename
        self.i = 0
        self.line = 1
        self.col = 1
        self.tokens = []
        self.depth = 0  # brackets that suppress newlines: ( and [

    # -- helpers ---------------------------------------------------------
    def peek(self, ahead=0):
        j = self.i + ahead
        return self.src[j] if j < len(self.src) else ""

    def advance(self):
        ch = self.src[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def emit(self, kind, text, line, col, value=None, off=None):
        self.tokens.append(Token(kind, text, line, col, value, off if off is not None else self.i))

    def fail(self, message, line=None, col=None):
        raise CompileError(message, line if line is not None else self.line,
                           col if col is not None else self.col)

    def last_significant(self):
        for t in reversed(self.tokens):
            if t.kind not in ("NL",):
                return t
        return None

    # -- main ------------------------------------------------------------
    def run(self):
        while self.i < len(self.src):
            ch = self.peek()

            if ch in " \t\r":
                self.advance()
                continue

            if ch == "\n":
                line, col = self.line, self.col
                self.advance()
                prev = self.last_significant()
                suppress = self.depth > 0
                if prev is not None and (
                    (prev.kind == "OP" and prev.text in _CONTINUATION)
                    or (prev.kind == "KW" and prev.text in _CONTINUATION)
                ):
                    suppress = True
                if not suppress and self.tokens and self.tokens[-1].kind != "NL":
                    self.emit("NL", "\\n", line, col)
                continue

            if ch == "-" and self.peek(1) == "-":
                self._line_comment()
                continue

            if ch == "-" and self.peek(1) == "/":
                self._block_comment()
                continue

            if ch == '"':
                self._string()
                continue

            if ch == "'":
                self._char()
                continue

            if ch.isdigit():
                self._number()
                continue

            if ch.isalpha() or ch == "_":
                self._identifier()
                continue

            if self._operator():
                continue

            self.fail("unexpected character %r" % ch)

        if self.tokens and self.tokens[-1].kind != "NL":
            self.emit("NL", "\\n", self.line, self.col)
        self.emit("EOF", "", self.line, self.col)
        return self.tokens

    # -- pieces ----------------------------------------------------------
    def _line_comment(self):
        while self.i < len(self.src) and self.peek() != "\n":
            self.advance()

    def _block_comment(self):
        line, col = self.line, self.col
        self.advance()
        self.advance()
        while self.i < len(self.src):
            if self.peek() == "/" and self.peek(1) == "-":
                self.advance()
                self.advance()
                return
            self.advance()
        self.fail("unterminated multi-line comment", line, col)

    def _identifier(self):
        line, col, off = self.line, self.col, self.i
        start = self.i
        while self.i < len(self.src) and (self.peek().isalnum() or self.peek() == "_"):
            self.advance()
        text = self.src[start:self.i]
        # `get-from` is one keyword (section 19); it contains a hyphen.
        if text == "get" and self.src[self.i:self.i + 5] == "-from":
            for _ in range(5):
                self.advance()
            self.emit("KW", "get-from", line, col, off=off)
            return
        if text in KEYWORDS:
            self.emit("KW", text, line, col, off=off)
        else:
            self.emit("IDENT", text, line, col, off=off)

    def _number(self):
        line, col, off = self.line, self.col, self.i
        start = self.i
        is_float = False

        if self.peek() == "0" and self.peek(1) in ("x", "X", "o", "O", "b", "B"):
            base_char = self.peek(1).lower()
            self.advance()
            self.advance()
            digits_start = self.i
            while self.peek().isalnum() or self.peek() == "_":
                self.advance()
            raw = self.src[digits_start:self.i].replace("_", "")
            base = {"x": 16, "o": 8, "b": 2}[base_char]
            try:
                value = int(raw, base)
            except ValueError:
                self.fail("malformed %s literal" % {"x": "hex", "o": "octal", "b": "binary"}[base_char],
                          line, col)
            self.emit("INT", self.src[start:self.i], line, col, value, off)
            return

        while self.peek().isdigit() or self.peek() == "_":
            self.advance()

        # a fraction, but not the `..` of a range
        if self.peek() == "." and self.peek(1) != "." and self.peek(1).isdigit():
            is_float = True
            self.advance()
            while self.peek().isdigit() or self.peek() == "_":
                self.advance()

        # an exponent
        if self.peek() in ("e", "E") and (
            self.peek(1).isdigit() or (self.peek(1) in ("+", "-") and self.peek(2).isdigit())
        ):
            is_float = True
            self.advance()
            if self.peek() in ("+", "-"):
                self.advance()
            while self.peek().isdigit():
                self.advance()

        raw = self.src[start:self.i].replace("_", "")
        if is_float:
            self.emit("FLOAT", self.src[start:self.i], line, col, float(raw), off)
        else:
            self.emit("INT", self.src[start:self.i], line, col, int(raw, 10), off)

    def _read_escape(self):
        """Consume the character after a backslash; return its byte as a string."""
        if self.i >= len(self.src):
            self.fail("unterminated escape sequence")
        ch = self.advance()
        if ch == "x":
            hex_digits = ""
            for _ in range(2):
                if self.peek() and self.peek() in "0123456789abcdefABCDEF":
                    hex_digits += self.advance()
            if not hex_digits:
                self.fail("\\x needs two hex digits")
            return chr(int(hex_digits, 16))
        if ch in _ESCAPES:
            return _ESCAPES[ch]
        self.fail("unknown escape '\\%s'" % ch)

    def _string(self):
        line, col, off = self.line, self.col, self.i
        self.advance()
        out = []
        while True:
            if self.i >= len(self.src) or self.peek() == "\n":
                self.fail("unterminated string", line, col)
            ch = self.advance()
            if ch == '"':
                break
            if ch == "\\":
                out.append(self._read_escape())
                continue
            out.append(ch)
        text = "".join(out)
        self.emit("STR", text, line, col, text, off)

    def _char(self):
        line, col, off = self.line, self.col, self.i
        self.advance()
        if self.i >= len(self.src) or self.peek() == "\n":
            self.fail("unterminated char literal", line, col)
        ch = self.advance()
        if ch == "\\":
            ch = self._read_escape()
        if self.peek() != "'":
            self.fail("char literal must hold exactly one byte", line, col)
        self.advance()
        value = ord(ch) & 0xFF
        self.emit("CHAR", ch, line, col, value, off)

    def _operator(self):
        for op in OPERATORS:
            if self.src.startswith(op, self.i):
                line, col, off = self.line, self.col, self.i
                for _ in op:
                    self.advance()
                if op in ("(", "["):
                    self.depth += 1
                elif op in (")", "]"):
                    self.depth = max(0, self.depth - 1)
                self.emit("OP", op, line, col, off=off)
                return True
        return False


def lex(source, filename="<source>"):
    return Lexer(source, filename).run()
