"""The baton type model and the conversion rules of specification sections 4 and 5."""

import re

_INT_SIZES = ("8", "16", "32", "64")


class Ty:
    """A baton type.  ``kind`` is one of int/uint/float/bool/char/str/void/unknown."""

    __slots__ = ("kind", "bits")

    def __init__(self, kind, bits=0):
        self.kind = kind
        self.bits = bits

    # -- predicates ------------------------------------------------------
    @property
    def is_int(self):
        return self.kind in ("int", "uint")

    @property
    def is_signed_int(self):
        return self.kind == "int"

    @property
    def is_unsigned_int(self):
        return self.kind == "uint"

    @property
    def is_float(self):
        return self.kind == "float"

    @property
    def is_numeric(self):
        return self.kind in ("int", "uint", "float")

    @property
    def is_scalar(self):
        return self.kind in ("int", "uint", "float", "bool", "char")

    @property
    def is_void(self):
        return self.kind == "void"

    # -- identity --------------------------------------------------------
    def __eq__(self, other):
        return isinstance(other, Ty) and self.kind == other.kind and self.bits == other.bits

    def __hash__(self):
        return hash((self.kind, self.bits))

    def __repr__(self):
        return "Ty(%s)" % self.name

    # -- names -----------------------------------------------------------
    @property
    def name(self):
        """The spelling used in baton source."""
        if self.kind == "int":
            return "i" if self.bits == 64 else "i%d" % self.bits
        if self.kind == "uint":
            return "u" if self.bits == 64 else "u%d" % self.bits
        if self.kind == "float":
            return "f" if self.bits == 64 else "f32"
        if self.kind == "bool":
            return "b"
        if self.kind == "char":
            return "c"
        if self.kind == "str":
            return "s"
        if self.kind == "void":
            return "void"
        return "?"

    @property
    def gloss(self):
        """The parenthesised word used in diagnostics, as in the spec's warning."""
        if self.kind == "int":
            return "int"
        if self.kind == "uint":
            return "uint"
        if self.kind == "float":
            return "float"
        if self.kind == "bool":
            return "bool"
        if self.kind == "char":
            return "char"
        if self.kind == "str":
            return "string"
        return "void"

    @property
    def c_name(self):
        """The C type this baton type compiles to (section 4)."""
        if self.kind == "int":
            return "int%d_t" % self.bits
        if self.kind == "uint":
            return "uint%d_t" % self.bits
        if self.kind == "float":
            return "double" if self.bits == 64 else "float"
        if self.kind == "bool":
            return "bool"
        if self.kind == "char":
            return "char"
        if self.kind == "str":
            return "const char*"
        return "void"

    @property
    def zero(self):
        if self.kind == "float":
            return "0.0"
        if self.kind == "bool":
            return "false"
        if self.kind == "char":
            return "'\\0'"
        if self.kind == "str":
            return '""'
        if self.kind == "int" or self.kind == "uint":
            return "0"
        return "0"


# -- shared instances ----------------------------------------------------
I = Ty("int", 64)
I8 = Ty("int", 8)
I16 = Ty("int", 16)
I32 = Ty("int", 32)
U = Ty("uint", 64)
U8 = Ty("uint", 8)
U16 = Ty("uint", 16)
U32 = Ty("uint", 32)
F = Ty("float", 64)
F32 = Ty("float", 32)
B = Ty("bool")
C = Ty("char")
S = Ty("str")
VOID = Ty("void")

_TYPE_RE = re.compile(r"^(?:[iu](?:8|16|32|64)?|f(?:32)?|b|c|s)$")


def is_type_name(text):
    return bool(_TYPE_RE.match(text))


def parse(text):
    """Turn a type spelling into a :class:`Ty`."""
    if text == "i":
        return I
    if text == "u":
        return U
    if text == "f":
        return F
    if text == "f32":
        return F32
    if text == "b":
        return B
    if text == "c":
        return C
    if text == "s":
        return S
    if len(text) >= 2 and text[0] in "iu" and text[1:] in _INT_SIZES:
        return Ty("int" if text[0] == "i" else "uint", int(text[1:]))
    raise KeyError(text)


def signed_range(bits):
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def unsigned_range(bits):
    return 0, (1 << bits) - 1


def fits_integer(value, ty):
    """Does the integer literal ``value`` fit the integer type ``ty`` (section 2)?"""
    if ty.kind == "int":
        lo, hi = signed_range(ty.bits)
    elif ty.kind == "uint":
        lo, hi = unsigned_range(ty.bits)
    else:
        return False
    return lo <= value <= hi


def can_auto_convert(src, dst):
    """The automatic conversions of section 5 (lossless widening)."""
    if src == dst:
        return True
    # int -> int
    if src.is_signed_int and dst.is_signed_int:
        return dst.bits >= src.bits
    if src.is_unsigned_int and dst.is_unsigned_int:
        return dst.bits >= src.bits
    if src.is_unsigned_int and dst.is_signed_int:
        return dst.bits > src.bits
    if src.is_signed_int and dst.is_unsigned_int:
        return False
    # ints -> float ("any int converts to a float"; f32 needs `as`)
    if src.is_int and dst.is_float:
        return dst.bits == 64
    # float -> float
    if src.is_float and dst.is_float:
        return src.bits <= dst.bits
    # char widens to u8 and larger ints
    if src.kind == "char" and (src.kind == "char" and dst.is_int):
        return dst.bits >= 8
    return False


def promote(a, b):
    """The result type of an arithmetic operation mixing ``a`` and ``b``.

    Returns ``None`` when the pair is not allowed without a cast.
    """
    if a == b:
        return a
    if a.is_numeric and b.is_numeric:
        # floats win; f32 mixed with an int has no silent conversion
        if a.is_float and b.is_float:
            return F if (a.bits == 64 or b.bits == 64) else F32
        if a.is_float or b.is_float:
            fty = a if a.is_float else b
            ity = b if a.is_float else a
            if fty.bits == 64:
                return F
            return None  # int with f32 needs an explicit cast
        # both integral
        if a.kind != b.kind:
            return None  # signed and unsigned do not mix silently
        return Ty(a.kind, max(a.bits, b.bits))
    return None


def unify(a, b):
    """The common type for a comparison or assignment-like context."""
    if a == b:
        return a
    if can_auto_convert(a, b):
        return b
    if can_auto_convert(b, a):
        return a
    return promote(a, b)
