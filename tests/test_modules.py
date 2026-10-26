import os
import tempfile

from baton import types as T
from baton.modules import _parse_btl


def parse(text, module="demo"):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "%s.btl" % module)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return _parse_btl(path, module)


def test_pointer_params_keep_their_name_out_of_the_type():
    ns = parse("""
        int demo_poll(int *type, int *key, const char *title);
    """)
    fn, = ns.functions
    assert fn.name == "poll"
    # int * -> *i, const char * -> *c; the parameter names are not swallowed
    assert [p.ty for p in fn.params] == [T.pointer_to(T.I), T.pointer_to(T.I),
                                         T.pointer_to(T.C)]
    assert [p.name for p in fn.params] == ["type", "key", "title"]


def test_common_c_types_and_opaque_pointers():
    ns = parse("""
        void* demo_window(const char *title, uint8_t r, size_t n);
        void demo_quit(void);
    """)
    window, quit_ = ns.functions
    assert window.ret == T.pointer_to(T.I)
    assert window.params[0].ty == T.pointer_to(T.C)
    assert window.params[1].ty == T.U8
    assert window.params[2].ty == T.U
    assert quit_.ret is None
    assert quit_.params == []


def test_only_module_prefixed_prototypes_are_exposed():
    ns = parse("""
        int demo_one(void);
        int other_two(void);
        static int demo_three(int x);
    """)
    assert [fn.name for fn in ns.functions] == ["one", "three"]
    assert all(fn.from_btl for fn in ns.functions)


def test_link_directive_is_collected_and_restricted():
    ns = parse("""
        /* baton:link -lSDL2 -L/opt/lib -o evil */
        int demo_init(void);
    """)
    assert ns.link_flags == ["-lSDL2", "-L/opt/lib"]
