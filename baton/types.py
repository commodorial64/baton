"""The baton type model and the conversion rules of specification sections 4 and 5."""

import re

_INT_SIZES = ("8", "16", "32", "64")
_C_IDENT = re.compile(r"[^A-Za-z0-9_]")


class Ty:
    """A baton type.

    Primitive types have a ``kind`` and a ``bits``.  The compound kinds are:

    ``pointer`` (``elem``), ``array`` (``elem`` and ``size``), ``list``
    (``elem``), ``struct`` (``name`` and ``args``), ``tuple`` (``elems``),
    ``file``, ``task`` and the temporary ``named``/``typeparam`` forms used
    while a declaration is being resolved.
    """

    __slots__ = ("kind", "bits", "elem", "size", "name_", "args", "elems")

    def __init__(self, kind, bits=0, elem=None, size=None, name=None,
                 args=(), elems=()):
        self.kind = kind
        self.bits = bits
        self.elem = elem
        self.size = size
        self.name_ = name
        self.args = tuple(args)
        self.elems = tuple(elems)

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

    @property
    def is_aggregate(self):
        return self.kind in ("struct", "array", "tuple")

    @property
    def is_list(self):
        return self.kind == "list"

    @property
    def is_array(self):
        return self.kind == "array"

    @property
    def is_pointer(self):
        return self.kind == "pointer"

    @property
    def is_indexable(self):
        return self.kind in ("list", "array", "pointer", "str")

    @property
    def is_struct(self):
        return self.kind == "struct"

    @property
    def is_file(self):
        return self.kind == "file"

    @property
    def is_task(self):
        return self.kind == "task"

    # -- identity --------------------------------------------------------
    def _key(self):
        return (self.kind, self.bits, self.size, self.name_, self.args,
                self.elem._key() if self.elem is not None else None,
                tuple(x._key() for x in self.elems))

    def __eq__(self, other):
        return isinstance(other, Ty) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

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
        if self.kind == "pointer":
            return "*" + self.elem.name
        if self.kind == "array":
            return "%s[%d]" % (self.elem.name, self.size)
        if self.kind == "list":
            return "%s[]" % self.elem.name
        if self.kind == "struct":
            if self.args:
                return "%s<%s>" % (self.name_, ", ".join(a.name for a in self.args))
            return self.name_
        if self.kind == "tuple":
            return ", ".join(x.name for x in self.elems)
        if self.kind == "file":
            return "File"
        if self.kind == "task":
            return "Task"
        if self.kind in ("named", "typeparam"):
            return self.name_
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
        return self.name

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
        if self.kind == "void":
            return "void"
        if self.kind == "pointer":
            return self.elem.c_name + " *"
        if self.kind == "array":
            return "bt_arr_" + self.mangle
        if self.kind == "list":
            return "BtList *"
        if self.kind == "struct":
            return self.name_
        if self.kind == "tuple":
            return "bt_tuple_" + self.mangle
        if self.kind == "file":
            return "BtFile *"
        if self.kind == "task":
            return "BtTask *"
        if self.kind in ("named", "typeparam"):
            return self.name_
        return "void"

    @property
    def mangle(self):
        """A stable fragment safe to use in a C identifier."""
        kind = self.kind
        if kind == "int":
            return "i" if self.bits == 64 else "i%d" % self.bits
        if kind == "uint":
            return "u" if self.bits == 64 else "u%d" % self.bits
        if kind == "float":
            return "f" if self.bits == 64 else "f32"
        if kind == "bool":
            return "b"
        if kind == "char":
            return "c"
        if kind == "str":
            return "s"
        if kind == "void":
            return "v"
        if kind == "pointer":
            return "p_" + self.elem.mangle
        if kind == "array":
            return "a%d_%s" % (self.size, self.elem.mangle)
        if kind == "list":
            return "l_" + self.elem.mangle
        if kind == "struct":
            base = _C_IDENT.sub("_", self.name_)
            if self.args:
                base += "__" + "__".join(a.mangle for a in self.args)
            return base
        if kind == "tuple":
            return "t_" + "_".join(x.mangle for x in self.elems)
        if kind == "file":
            return "File"
        if kind == "task":
            return "Task"
        return _C_IDENT.sub("_", self.name_ or "x")

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
        if self.kind == "pointer":
            return "NULL"
        if self.kind == "list":
            return "NULL"
        if self.kind == "file":
            return "NULL"
        if self.kind == "task":
            return "NULL"
        if self.kind in ("array", "struct", "tuple"):
            return "(%s){0}" % self.c_name
        return "0"

    # -- element access --------------------------------------------------
    def element_type(self):
        if self.kind in ("pointer", "array", "list"):
            return self.elem
        if self.kind == "str":
            return C
        return None


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
FILE = Ty("file")
TASK = Ty("task")


def pointer_to(elem):
    return Ty("pointer", elem=elem)


def array_of(elem, size):
    return Ty("array", elem=elem, size=size)


def list_of(elem):
    return Ty("list", elem=elem)


def struct_type(name, args=()):
    return Ty("struct", name=name, args=args)


def tuple_type(elems):
    return Ty("tuple", elems=elems)


def named(name):
    return Ty("named", name=name)


def typeparam(name):
    return Ty("typeparam", name=name)


_TYPE_RE = re.compile(r"^(?:[iu](?:8|16|32|64)?|f(?:32)?|b|c|s)$")


def is_type_name(text):
    return bool(_TYPE_RE.match(text))


def parse(text):
    """Turn a primitive type spelling into a :class:`Ty`."""
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
    if src.kind == "char" and dst.is_int:
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


def substitute(ty, env):
    """Replace type parameters throughout a type."""
    if ty is None:
        return None
    if ty.kind in ("named", "typeparam") and ty.name_ in env:
        return env[ty.name_]
    if ty.kind == "pointer":
        return pointer_to(substitute(ty.elem, env))
    if ty.kind == "array":
        return array_of(substitute(ty.elem, env), ty.size)
    if ty.kind == "list":
        return list_of(substitute(ty.elem, env))
    if ty.kind == "struct" and ty.args:
        return struct_type(ty.name_, [substitute(a, env) for a in ty.args])
    if ty.kind == "tuple":
        return tuple_type([substitute(x, env) for x in ty.elems])
    return ty


def constraint_ok(ty, constraint):
    """Does ``ty`` satisfy the built-in ``num`` / ``ord`` constraint?"""
    if constraint is None:
        return True
    if constraint == "num":
        return ty.is_numeric
    if constraint == "ord":
        return ty.is_numeric or ty.kind in ("char", "str")
    return False
