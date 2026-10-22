"""Error and warning formatting.

The spec shows the exact shape of a diagnostic (section 3):

    warning: hello.bt:3: no type prefix on 'x', inferred 'i' (int)
        3 | local x = 5
          | ^^^^^ try: i local x = 5
"""

import sys


class CompileError(Exception):
    def __init__(self, message, line=None, col=None, span=None, hint=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.span = span  # number of carets, when known
        self.hint = hint


class Reporter:
    """Collects diagnostics for one source file."""

    def __init__(self, filename, source, warnings="default", stream=None):
        self.filename = filename
        self.source = source
        self.lines = source.split("\n")
        self.warnings = warnings  # "default", "none", "error"
        self.stream = stream if stream is not None else sys.stderr
        self.errors = 0
        self.warning_count = 0

    # -- rendering -------------------------------------------------------
    def _show(self, label, line, col, message, span=None, hint=None):
        loc = "%s:%d" % (self.filename, line) if line else self.filename
        print("%s: %s: %s" % (label, loc, message), file=self.stream)
        if line and 1 <= line <= len(self.lines):
            text = self.lines[line - 1]
            gutter = "%5d | " % line
            print(gutter + text, file=self.stream)
            if col:
                if span:
                    carets = "^" * span
                else:
                    carets = "^"
                trailer = (" " + hint) if hint else ""
                print(" " * 5 + " | " + " " * (col - 1) + carets + trailer, file=self.stream)

    # -- entry points ----------------------------------------------------
    def error(self, exc_or_message, line=None, col=None, span=None, hint=None):
        if isinstance(exc_or_message, CompileError):
            e = exc_or_message
            line, col, span, hint = e.line, e.col, e.span, e.hint
            message = e.message
        else:
            message = exc_or_message
        self.errors += 1
        self._show("error", line, col, message, span, hint)

    def warn(self, message, line=None, col=None, span=None, hint=None):
        if self.warnings == "none":
            return
        if self.warnings == "error":
            self.error(message, line, col, span, hint)
            return
        self.warning_count += 1
        self._show("warning", line, col, message, span, hint)

    @property
    def failed(self):
        return self.errors > 0
