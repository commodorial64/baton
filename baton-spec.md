# Baton Language Specification

**Version:** 0.1 (draft)

Baton is a statically typed, general-purpose, low-level language that compiles to C and is built with gcc. It has Lua-flavored variable declarations, single-letter type prefixes, brace-delimited blocks, and compiler-managed memory.

**Status:** everything in this document was decided in design discussion. Section 27 lists what is not designed yet.

---

## 1. Compilation model

```
hello.bt -> lexer -> parser -> type checker -> C codegen -> gcc -> binary
```

- Source files use the `.bt` extension.
- The compiler is written in Python, invoked as `baton build hello.bt`. It emits `hello.c` and shells out to `gcc`.
- `baton man` shows this document; `baton man 13` shows a single section.
- Every baton construct maps directly onto C, so there is no runtime cost beyond reference counting (section 13).
- Warnings can be silenced with `-W none` or promoted to errors with `-W error`.

## 2. Lexical rules

### Comments

```
-- single-line comment

-/ multi-line
   comment /-
```

- `--` always starts a comment. There is no `--` decrement operator, and negating a negative is written `a - -b` with a space.
- Multi-line comments do not nest.

### Identifiers

Letters, digits and `_`, not starting with a digit, and not a keyword. `snake_case` is the convention but is not enforced.

### Keywords

```
local const fn ns functions struct
if elf else while for in by loop break continue return
as and or not true false det
```

`elf` is the else-if keyword, so it cannot be used as a name.

### Literals

| Kind | Example | Default type |
|---|---|---|
| Integer | `42` | `i` |
| Float | `2.5` | `f` |
| Bool | `true`, `false` | `b` |
| Char | `'a'` | `c` |
| String | `"baton"` | `s` |

Other integer bases and separators:

```
0xFF    0o755    0b1010    1_000_000
```

- Hex (`0x`), octal (`0o`) and binary (`0b`) literals default to `i`, like decimal ones.
- Underscores may appear between digits: `1_000_000`, `0xFF_FF`.
- String and char escapes: `\n`, `\t`, `\r`, `\\`, `\"`, `\'`, `\0`, and `\xHH` for a raw byte (so `'\x41'` is `A`).
- Source files are UTF-8. Strings are byte strings: a literal keeps its bytes as written, and `c` is a single byte. Valid UTF-8 text passes through unchanged.

Integer literals that do not fit their target type are compile errors (for example `u8 local d = 256`).

## 3. Variables

### Declaration

```
<type> local <name> = <value>
<type> const <NAME> = <value>
```

```
i local integer = 1          -- local int named "integer", value 1
f local ratio = 2.5
b local done = false
s local name = "baton"
i const MAX = 100            -- immutable, compile-time
```

- `local` declares a mutable variable. `const` declares an immutable one.
- The type is a single-letter prefix (section 6).
- **The prefix is optional.** When omitted, the type is inferred from the value, the code still compiles, and the compiler emits a warning showing the inferred type and the fix:

```
warning: hello.bt:3: no type prefix on 'x', inferred 'i' (int)
    3 | local x = 5
      | ^^^^^ try: i local x = 5
```

- The same rule applies to `const`.

### Zero-initialization

A declaration with no value is set to the zero value of its type (`0`, `0.0`, `false`, `""`, the null address for pointers).

```
i local count                -- 0
```

The prefix is **required** here, since there is no value to infer from. Omitting it is a hard error.

### Multiple assignment

```
i local a, b = 1, 2
a, b = b, a                  -- swap
```

`i local a, b = 1, 2` covers both variables. Variables of different types need separate declarations — except when unpacking a multiple return (sections 5, 8, 23), where each name takes its own type: `i local n, b ok = tryi("42")`.

### Scope

- Variables are block scoped, from their declaration to the closing `}`.
- Every variable must be declared with `local` or `const` before use. Assigning to an undeclared name is a compile error.
- A nested block may shadow an outer name. Redeclaring a name in the same block is an error.

```
i local x = 1
do_something()
{
    i local x = 2            -- ok, shadows the outer x
}
i local x = 3                -- error, already declared in this block
```

### Globals

A declaration at file top level — outside every function — is a **global**. The keywords don't change: top-level `local` and `const` are how you write one.

```
i const MAX_ENEMIES = 32     -- compile-time constant
i local score = 0            -- mutable global
```

- Globals are visible from their declaration to the end of the file, and are read and written like any other variable. A `local` inside a function may shadow one.
- Repeating a name at top level is an error, like any other redeclaration in the same block.
- A global with no value is zero-initialized, same as everywhere else.
- `const` globals must have a constant value and compile to `static const`. A non-constant initializer is hoisted into a generated `bt_init()` that runs before `main`, so `i local next_id = read_seed()` at top level just works — you never see the generated function.
- Globals are file-scoped. What happens across files waits on imports (section 19).

## 4. Types

| Letter | Type | C output |
|---|---|---|
| `i`, `i8`, `i16`, `i32`, `i64` | signed integer (`i` is 64-bit) | `int64_t`, `int8_t`, ... |
| `u`, `u8`, `u16`, `u32`, `u64` | unsigned integer (`u` is 64-bit) | `uint64_t`, `uint8_t`, ... |
| `f`, `f32` | float (`f` is 64-bit) | `double`, `float` |
| `b` | bool | `bool` |
| `c` | char (single byte, ASCII) | `char` |
| `s` | string | `baton_str` |

- `i` is 64-bit, so it is not the same as C's `int`. For a 32-bit int use `i32`.
- Custom types (structs) are written with their full name, like `Point local p`.
- Signed integer overflow wraps (the compiler uses `-fwrapv`).
- There is no `nil` or `null` literal. A variable always has a value; a zeroed pointer's value is the null address, which `isnull` tests (section 20).

### Bools have no truthiness

Conditions must be of type `b`. `if count {` is an error. Write `if count != 0 {`.

## 5. Conversions

### Automatic (lossless widening)

- Smaller ints widen to larger ints (`i8` to `i16` to `i32` to `i`, and the same for `u`).
- An unsigned int widens to a larger signed int.
- Any int converts to a float, and `f32` converts to `f`.
- A `c` widens to `u8` and larger ints.
- Mixed arithmetic promotes to the wider type, so `i + f` gives `f`.
- Literals adapt to context: `f local x = 2` is fine.

A 64-bit `i` converted to `f` can lose precision above 2^53. This is allowed silently.

### Explicit with `as`

```
i local count = 300
u8 local small = count as u8     -- narrowing, truncates
i local whole = 2.7 as i         -- float to int, drops the fraction
u local m = count as u           -- signed to unsigned
```

`as` is required for narrowing, float to int, and signed to unsigned (or back) at the same size. Anything involving `b` or `s` never converts silently.

### Conversion functions

```
i local n = toi("42")
f local x = tof("2.5")
s local text = tos(42)
b local flag = tob("true")
i local k = toi(2.7)
```

- The `to` functions accept anything that makes sense and generate the right C (`strtoll`, `snprintf`, a plain cast).
- On bad input they return the zero value (`0`, `0.0`, `false`, `""`).
- `as` and the `to` functions overlap for numbers. Both are kept.

### Checked parse functions

```
i local n, b ok = tryi("42")      -- n = 42, ok = true
i local m, b bad = tryi("hello")  -- m = 0,  ok = false
f local x, b ok2 = tryf("2.5")
```

- `tryi` and `tryf` are the checked forms of `toi` and `tof`: they return the value plus a `b` saying whether the input parsed.
- `toi` and `tof` stay as the convenient unchecked forms.

## 6. Strings

- `s` is a pointer plus a length, so length is O(1) and slicing is free. String literals also carry a null terminator so they can be passed to C functions.
- Strings are immutable.
- `==`, `!=` compare contents (not addresses). `<`, `>`, `<=`, `>=` compare bytes in ASCII order, so `"Zebra" < "apple"` is true.
- `+` joins strings.
- Comparing a string to a number is a type error.

String helpers live in the `str` namespace (section 22): `str.lower`, `str.upper`, `str.has`, `str.starts`, `str.ends`, `str.trim`, `str.split`, `str.join`.

## 7. Operators

- **Arithmetic:** `+ - * / % **`
- **Comparison:** `== != < > <= >=`
- **Logic:** `and or not` (short-circuit)
- **Bitwise:** `&`, `|`, `^`, `~`, `<<`, `>>`
- **Assignment:** `= += -= *= /= %= **=`

Notes:

- `/` on two ints is integer division, truncating toward zero (`7 / 2` is `3`, `7 / 2.0` is `3.5`).
- There is no `++` or `--`. Use `x += 1`.
- `**` on ints compiles to a generated helper function, since C has no integer power operator.

### Precedence (tightest first)

1. `.` `[]` `()`
2. `**`
3. unary `-`, `*` (deref), `&` (address-of), `not`, `~`, then `as`
4. `*` `/` `%`
5. `+` `-`
6. `<<` `>>`
7. `&`, then `^`, then `|`
8. `<` `<=` `>` `>=` `==` `!=`
9. `and`
10. `or`

Bitwise operators bind tighter than comparisons, unlike C: `a & b == c` means `(a & b) == c`. The generated C is fully parenthesized.

## 8. Functions

```
fn add(i a, i b) -> i {
    return a + b
}
```

- The parameter list uses the type-letter-first style, matching declarations.
- `->` introduces the return type. A function that returns nothing leaves it off, and compiles to a `void` function.
- Compiles to `int64_t add(int64_t a, int64_t b) { return a + b; }`.
- Entry point is `fn main() -> i`, and its return value is the exit code.

### Multiple return values

```
fn divmod(i a, i b) -> i, i {
    return a / b, a % b
}

i local q, r = divmod(17, 5)
```

Compiled to a generated struct holding both values.

### Return determiner

A return statement can state its type with the same arrow used in function signatures:

```
return a + b -> i
```

It is optional, since the compiler works the type out from the expression.

### Calling C directly

```
extern fn puts(s) -> i
extern fn rand() -> i
```

- `extern fn` declares a function that already exists in C. The baton name is the C name, unchanged.
- The compiler emits the prototype and a plain call; gcc resolves it at link time. This is the escape hatch for libc and other C libraries.
- `extern fn` takes baton types, pointers included (section 20).

## 9. Namespaces

```
ns calc(i a, i b) -> det {
    functions {
        add()      { return a + b -> i }
        subtract() { return a - b }
        multiply() { return a * b }
        divide()   { return a / b }
        power()    { return a ** b }
        scale(i k) { return (a + b) * k }
    }
}

print(calc.add(5, 5))           -- 10
print(calc.scale(2, 3, 10))     -- 50
```

- `ns` declares a namespace. The parameters on the `ns` line are shared by every function inside.
- Empty `()` inherits those parameters. A function can add its own, which go after the inherited ones (`scale(i k)` is called with `a`, `b`, then `k`).
- `det` (determined) is a wildcard return type. The compiler works it out from each function's return statement.
- Functions are called as `calc.add(5, 5)`.
- Compiles to prefixed C functions: `int64_t calc_add(int64_t a, int64_t b)`.
- A function that does not fit the shared parameters can be a normal `fn` outside the namespace.
- The `functions { }` wrapper stays. It marks what belongs to the namespace, and `ns` can also hold `const` members — the standard `math.pi` and `math.e` use that (section 22).
- User namespaces cannot reuse a standard library namespace name such as `math` or `str` (section 22); the examples here use `calc`.
- A baton namespace and a C `.btl` module are interchangeable: both are called `calc.add(1, 2)` (section 19).

## 10. Control flow

Conditions must be `b`. Braces are always required. There are no parentheses around conditions.

### If / elf / else

```
if x > 10 {
    print("big")
} elf x > 5 {
    print("medium")
} else {
    print("small")
}
```

### While

```
i local n = 0
while n < 5 {
    n += 1
}
```

### For with ranges

```
for i in 0..10 { }               -- 0 through 9
for i in 0..=10 { }              -- 0 through 10
for i in 0..20 by 5 { }          -- 0, 5, 10, 15
for i in 10..0 by -1 { }         -- 10 down to 1
```

- The loop variable is created automatically, takes its type from the range, and is read-only in the body.
- A negative step counts down.
- `for` also iterates arrays and lists (section 13).

### Loop, break, continue

```
loop {
    s local line = input()
    if line == "quit" { break }
    if line == "" { continue }
    handle(line)
}
```

`loop` is a forever-loop. `break` leaves the nearest loop. `continue` skips to the next pass. Loop labels (`outer:` with `break outer`) are part of the design from the discussion.

### Match

```
match n {
    0        { print("zero") }
    1..=9    { print("small") }
    else     { print("big") }
}

match cmd {
    "start"  { start() }
    "quit"   { quit() }
    else     { print("unknown command") }
}
```

- Arms are constants: integers, chars, strings, or ranges (`1..=9`). An arm may list several values separated by commas (`1, 3, 5`).
- `else` is required when the arms cannot cover every value of the type — in practice, always for `i` and `s`.
- Exactly one arm runs. There is no fallthrough.
- Compiles to a switch for integers and a chain of comparisons for strings.

## 11. Structs

```
struct Point {
    i x
    i y
}

Point local p = {x = 1, y = 2}
Point local origin               -- zero-initialized
p.x = 10
```

- Fields are written like parameters, with the type letter first.
- Structs copy by value, like C.
- Fields can be any type, including other structs and arrays.
- Compiles to `typedef struct { int64_t x; int64_t y; } Point;`.

## 12. Arrays and lists

A number in the brackets means fixed size. Empty brackets means growable.

```
i[3] local fixed = {10, 20, 30}  -- fixed size, on the stack
i[5] local zeros                 -- zero-initialized
i[] local list = {1, 2, 3}       -- growable

push(list, 4)
pop(list)                        -- removes and returns the last item
len(list)
list[0]                          -- first item
```

- Indexing is **0-based**.
- Out-of-range access is a runtime error with a clear message, not silent memory corruption. A release flag may turn the checks off.
- Iteration:

```
for x in list { }                -- each value
for i, x in list { }             -- index and value
```

- `list[1..3]` is a slice, a view onto the same data with no copying.
- A fixed array is a plain C array. A list compiles to a struct holding a pointer, length and capacity.

## 13. Memory management

Memory is managed automatically through **reference counting**, inserted by the compiler into the generated C. You never write `free` (for refcounted storage — raw blocks are section 20).

```
s local a = "hello" + " world"   -- allocated, count 1
s local b = a                    -- shared, count 2
-- end of scope: both released, memory freed
```

- **Strings** are immutable and shared freely.
- **Lists share on assignment**, like Python. `list2 = list1` points at the same data, so changing one changes the other.
- **`clone()`** makes an independent copy: `list2 = list1.clone()`. A clone is a full copy including any nested lists. Strings inside stay shared, which is safe because they never change.
- Passing a list to a function shares it, so changes made inside are visible to the caller.
- Returning a list hands it to the caller without a copy.
- String literals live in the program itself and are never counted or freed.
- Fixed arrays and structs stay on the stack and copy by value, with no counting.

The raw escape hatch — `*T`, `alloc`, `free` — lives in section 20, deliberately kept separate: pointer operations never touch reference counting.

## 14. Methods

Functions can be called on a value with a dot:

```
i[] local backup = list.clone()
```

This works alongside namespaces (`calc.add(5, 5)`), since the compiler knows whether the name on the left is a namespace or a variable.

For v0.1 list operations stay free functions (`push(list, 4)`, `len(list)`). Calling them as methods (`list.push(4)`) is postponed until methods on structs have proven themselves.

## 15. Example program

```
struct Point {
    i x
    i y
}

ns calc(i a, i b) -> det {
    functions {
        add()      { return a + b }
        scale(i k) { return (a + b) * k }
    }
}

fn dist2(Point p, Point q) -> i {
    i local dx = p.x - q.x
    i local dy = p.y - q.y
    return dx * dx + dy * dy
}

fn main() -> i {
    Point local a = {x = 0, y = 0}
    Point local b = {x = 3, y = 4}
    print("dist2:", dist2(a, b))           -- 25

    i[] local nums = {1, 2, 3}
    i[] local backup = nums.clone()
    push(nums, 4)

    i local total = 0
    for n in nums {
        total += n
    }
    print("total:", total)                  -- 10
    print(calc.add(5, 5))                  -- 10

    if total > 5 and len(backup) == 3 {
        print("ok")
    } elf total == 0 {
        print("empty")
    } else {
        print("small")
    }
    return 0
}
```

`print` is covered in section 17.

## 16. Generated C reference

| Baton | C |
|---|---|
| `i local x = 5` | `int64_t x = 5;` |
| `i const MAX = 100` | `static const int64_t MAX = 100;` |
| top-level `i local x = f()` | `static int64_t x;`, set by the generated `bt_init()` before `main` |
| `i local count` | `int64_t count = 0;` |
| `fn add(i a, i b) -> i` | `int64_t add(int64_t a, int64_t b)` |
| `calc.add(5, 5)` | `calc_add(5, 5)` |
| `for i in 0..10` | `for (int64_t i = 0; i < 10; i++)` |
| `for i in 0..=10` | `for (int64_t i = 0; i <= 10; i++)` |
| `loop` | `for (;;)` |
| `a, b = b, a` | swap through generated temporaries |
| `a == b` on strings | length check plus `memcmp` |
| `x as u8` | `(uint8_t)x` |
| `*i local p = &x` | `int64_t* p = &x;` |
| `*p = 5` | `*p = 5;` |
| `p.x` (p is `*Point`) | `p->x` |
| `alloc(i, 10)` | `bt_alloc(10, sizeof(int64_t))` — zero-fills, panics on failure |
| `free(p)` | `free(p)` |
| `isnull(p)` | `(p == NULL)` |
| `fn bigger<T>(T a, T b) -> T` | one specialized function per instantiation (`bt_bigger__i`, `bt_bigger__f`) |

## 17. Input and output

- `print(...)` takes any number of `s`, `i`, `f`, `b` and `c` values, prints them separated by spaces, and ends the line. `b` prints as `true` / `false`. No `tos()` wrapping is needed for output.
- `write(...)` is the same without the trailing newline.
- `input() -> s` reads one line from stdin, strips the newline, and returns `""` at EOF.

```
write("name: ")
s local name = input()
print("hello,", name)
```

Named files live in section 23.

## 18. Errors and panics

- There are no exceptions. Functions report failure through return values: the checked parse functions from section 5 (`tryi`, `tryf`) are the pattern.
- A runtime failure — division by zero, index out of range, dereferencing a null pointer — prints a message with the source line number to stderr and exits with a nonzero status.
- `panic("message")` does the same on demand, for conditions the compiler cannot check for you.
- `try` / `?`-style propagation is not part of v0.1.

## 19. Modules and imports

Programs split across files. There are two kinds of module file:

- `.bt` — written in baton.
- `.btl` — written in C. Since baton compiles to C anyway, a library is just C.

A module is brought in with one top-level statement:

```
mod get-from "lib/calc.btl"           -- calc.add(1, 2), calc.scale(2, 3)
mod m get-from "lib/calc.btl"         -- m.add(1, 2) instead
```

The shape is borrowed from Luau's `local RS = game:GetService("ReplicatedStorage")`: the `mod m` is the `local RS` (the binding), `get-from` is the `game:GetService` (the fetch), and the path is the service name (what identifies the thing being fetched).

- No `local` — just `mod`.
- **The module's name comes from the file name:** `calc.btl` is the module `calc`. Nothing after `mod` means "use the file's name".
- Anything after `mod` is an alias: `mod m get-from "..."` binds `m` and nothing else. The alias only renames the baton-side surface — `m.add(1, 2)` still compiles to `calc_add(1, 2)`.
- Top-level only, file-scoped: visible from the `mod` line to the end of the file, like globals (section 3).
- Paths are relative to the file doing the importing.
- Each file is compiled once, no matter how many files import it. Cycles between `.bt` files are a compile error.

### `.btl` — C modules

- The file name is the C prefix: `calc.btl` provides `calc_add`, `calc_scale`, ... — the exact convention a baton `ns` generates (section 9), so a namespace and a `.btl` are interchangeable: same call syntax, either one can provide it.
- The compiler parses the `.btl`'s top-level prototypes whose names start with `<modname>_` and maps C types to baton types: `int64_t` → `i`, `double` → `f`, `bool` → `b`, `char` → `c`, `baton_str` → `s`, `int8_t`..`int32_t` and `uint8_t`..`uint32_t` → `i8`..`i32` / `u8`..`u32`, and pointers as `T *` → `*T` (`int64_t *` → `*i`, `char *` → `*c`).
- A prototype the compiler cannot map is included in the C but not callable from baton — not an error, so `.btl` files are free to hold C-only helpers. `void *` maps to `*i` as an opaque handle.
- The generated C starts with `#include "path/to/calc.btl"`. One gcc invocation; include guards make repeated imports harmless.
- A `.btl` may carry its own implementations and be header-only; the compiler only reads the prototypes, and the include supplies the code. This keeps a package to one gcc invocation.
- A `.btl` may request linker flags with a comment: `/* baton:link -lSDL2 */`. Every imported module contributes its flags to the single gcc command.
- Installed packages live under `~/.local/share/baton/lib` (override with `BATON_LIB`). `baton libinstall <pkg>` fetches `<pkg>/<pkg>.btl` (or `.bt`) plus optional `constants.bt` and `<pkg>.c`, and `baton libs` lists them. A relative import that does not exist next to the importing file is looked up there, so `mod sharpe get-from "sharpe/sharpe.btl"` works after installation.

### `.bt` — baton modules, `expose` instead of `return`

Where Luau's module script ends in `return { ... }`, a `.bt` module publishes its surface with one `expose` statement:

```
fn to_hex(i n) -> s { ... }          -- private helper

ns calc(i a, i b) -> det {
    functions {
        add() { return a + b }
        hex() { return to_hex(add()) }   -- helper chip in, stays private
    }
}

expose calc
```

- `expose` lists what the module publishes — in practice the namespace (a struct or two may join it). It is explicit: everything not listed is private to the file.
- Private names are still full citizens inside their file: the exposed namespace's functions call `to_hex` freely, the importer gets `calc` and never `to_hex`. That is how a module keeps the helpers it wants without dragging them into anyone else's namespace.
- The file name must match an exposed name: `calc.bt` must `expose calc`. Importing `lib/calc.bt` therefore binds `calc` (or the alias, with `mod m get-from ...`).
- A module may `expose` something it itself imported, so libraries can layer.

## 20. Pointers

Pointers are the raw C escape hatch — the same `T *` gcc uses — for C interop and for the parts of a game engine that manage memory by hand. There is **no `unsafe` block**: baton marks danger with runtime checks, not syntax. Pointers are opt-in by type, they never touch reference counting (section 13), and `alloc` / `free` / `isnull` / `cstr` are builtins like `print` — no new keywords.

### Types and operators

```
i local x = 5
*i local p = &x            -- pointer to x
print(*p)                  -- 5
*p = 10                    -- writes through
print(x)                   -- 10
```

- The type is `*T` — `*i`, `*f`, `*Point` — and compiles to `int64_t*`, `double*`, `Point*`. Pointer to pointer is `**i`.
- `&v` is address-of, and it needs storage: a variable, global, struct field, or array element — not a temporary.
- `*p` is dereference: reading `*p` yields the value, `*p = v` stores it.
- `p.x` on a `*Point` auto-dereferences (it compiles to `p->x`). Field access is the only automatic deref — passing `*Point` where `Point` is expected is a type error, so write `*p`.
- `p[i]`, `p + n`, `p - n` and `p1 - p2` are raw pointer arithmetic. Nothing is bounds-checked there: a raw pointer carries no length, unlike `s` and lists, which do.
- Pointers of the same type compare with `==` and `!=`.
- Converting between pointer types needs `as` (`buf as *c`). Converting a pointer to or from an integer is not in v0.1.
- In expressions `**` stays the power operator, so double deref is written `*(*pp)`. In a type, `**i` reads pointer-to-pointer.

### The null pointer

- A pointer's zero value is the null address: `*i local p` starts out null, and pointer-typed struct fields zero-fill like every other field.
- There is still no `null` literal to write (section 4). Baton code reaches null only by leaving a pointer zeroed; C reaches it by returning one.
- `isnull(p) -> b` tests for it — the check you put on anything coming back from an `extern fn`.
- Dereferencing or indexing a null pointer is a runtime error with a line number, like division by zero (section 18).

### alloc and free

```
*i local buf = alloc(i, 10)       -- ten int64_t, zero-filled
*Point local q = alloc(Point, 1)  -- one Point

free(buf)
free(q)
```

- `alloc(TYPE, COUNT)` returns `*TYPE`. Its first argument is a type, parsed like the operand of `as`. It zero-fills — the zero-init rule extends to the heap — and allocation failure is a panic, not a null return.
- `free(p)` releases one `alloc` block. That is the whole deal: baton never reclaims raw memory for you, and `free` is only for what `alloc` returned. Refcounted storage is released by refcounting (section 13), never by you.
- `&list[0]` does not keep the list alive. Pointers and reference counting do not mix.
- Double-free and use-after-free are **not** detected in v0.1. Null is checked, lifetimes are yours — that is the bargain of this section.

### Into C

- `extern fn` takes pointer types in its prototypes: `extern fn scopy(*c dst, *c src) -> *c`.
- `cstr(s) -> *c` hands C the null-terminated bytes of a string (strings store a trailing null byte, so it is free — section 6). It is valid while the string lives; never `free` it.

## 21. Generics

A function or struct written once, compiled for every type actually used.

### Type parameters

```
fn bigger<T>(T a, T b) -> T {
    if a > b { return a }
    return b
}

struct Bag<T> {
    T[] items
}

i local big = bigger(3, 7)              -- T worked out from the arguments
f local small = bigger(2.5, 7.5)        -- same source, another instantiation
Bag<s> local bag = { items = {"a", "b"} }
```

- A capitalized name in `<...>` is a type parameter: `fn bigger<T>`, `struct Bag<T>`, `fn Bag<T>.at(self, i i) -> T`. Capitals are already the convention for types, so `T` reads as one.
- Call sites infer the type from the arguments. When there is nothing to infer from, say it: `bigger<i>(3, 7)`.
- Codegen is **monomorphization**: one C function per instantiation (`bt_bigger__i`, `bt_bigger__f`), so generics cost nothing at runtime — the same promise as section 1. The type argument must be legal in C, which is any baton type.
- Without a constraint, `if a > b` inside a generic body means every instantiation must support `>`, and a violation is reported at the instantiation that breaks it, by name. With a constraint the same body is checked once, at the definition (section 25).
- In a type, `>>` is two closes, never a shift: `Bag<Bag<i>>` is fine (`a >> b` in an expression is untouched).

## 22. Standard library

The standard library ships with the compiler and is **always in scope — no import needed** (user modules still use `mod get-from`, section 19). It is the Luau arrangement: `math`, `str`, `list` are just there.

**Builtins** (always in scope, compiler-emitted): `print`, `write`, `input`, `panic`, the `to*` / `try*` conversions, `len`, `push`, `pop`, `clone`, `isnull`, `cstr`, `alloc`, `free`, and the file builtins (section 23).

**Namespaces:**

| Namespace | Members |
|---|---|
| `math` | `sqrt` `abs` `floor` `ceil` `round` `min` `max` `sin` `cos` `tan` `atan` `atan2` `pow` `exp` `log`, const `pi` `e` |
| `str` | `lower` `upper` `has` `starts` `ends` `trim` `split` `join` |
| `list` | `sort` `reverse` `indexof` |
| `rand` | `int(lo, hi)` `float()` `seed(i)` |
| `time` | `now()` (ms since epoch) `tick()` (ms since program start) |
| `fs` | `exists` `list` `mkdir` `remove` `err` |
| `task` | `spawn` `wait` `join` `stop` |

```
print(math.sqrt(2))            -- 1.4142135623730951
print(str.upper("baton"))      -- BATON

i[] local nums = {5, 3, 1}
list.sort(nums)                -- {1, 3, 5}, in place
i local roll, b ok = rand.int(1, 6)
```

- The library is written in baton and C (`.bt` veneers over `.btl` cores — it dogfoods section 19) and ships with the compiler. Only the namespaces a program actually references get compiled in.
- `list.sort` and `list.reverse` work in place on lists of ordered primitives; `list.indexof` returns `i, b` like `tryi` (`-1` conventions are not baton). No comparator functions exist yet (functions are not values), so complex ordering waits.
- `rand` is C's `rand` — fine for games, not for cryptography.
- Using `math` links libm: the compiler adds `-lm` when it is referenced.
- Std names shadow like any outer name (a local `math` inside a function is legal); redefining one at top level is an error (section 3).

## 23. Files

```
File local f, b ok = fopen("log.txt", "w")
if not ok {
    panic("cannot open log.txt")
}
f.write("line 1\n")
f.close()

s local text, b got = readfile("config.txt")
b saved = writefile("out.txt", text)

File local log = f                       -- shares the handle (refcounted)
loop {
    s local line, b more = f.line()
    if not more { break }
    print(line)
}
```

- `fopen(path, mode) -> File, b ok` — modes `"r"`, `"w"`, `"a"`. `ok` is false for a missing file or bad permissions: the checked-return pattern of sections 5 and 18, not exceptions.
- `File` is opaque (no visible fields) and **refcounted** like strings and lists (section 13): assignment shares the handle, and the last reference going out of scope closes it. The explicit `f.close()` is for when you need it flushed now, not for bookkeeping.
- Operations: `f.write(s) -> b ok` (false means the write failed), `f.line() -> s, b more` (next line without its newline; `more` is false at EOF), `f.read(i n) -> s` (up to n bytes, `""` at EOF), `f.close()`.
- Using a closed or never-opened `File` is a runtime error with a line number (section 18) — the same stance as a null deref. The zero value of `File` is the closed handle.
- `readfile(path) -> s, b` and `writefile(path, s) -> b` handle a whole file in one call.
- Paths are relative to the program's working directory (imports in section 19 are relative to the importing file).
- Strings are bytes (section 2), so binary files round-trip unchanged. Writes are buffered by C stdio; the file is complete after `close`.
- Seeking, directories, and error detail live in section 24.

## 24. File extras

```
File local f, b ok = fopen("data.bin", "r")
if ok {
    f.seek(100)
    s local chunk = f.read(64)
    print("at", f.tell())
    f.close()
}

s[] local entries, b listed = fs.list("assets")
if not listed { print(fs.err()) }

if not fs.exists("save.dat") { fs.mkdir("saves") }
fs.remove("tmp.dat")
```

- `f.seek(i pos) -> b ok` moves to an absolute byte position from the start of the file; `f.tell() -> i` reports the current one. A relative seek is `f.seek(f.tell() + delta)`. Reads at the end still return `""` as before.
- The `fs` namespace is the directory side: `fs.exists(path) -> b`, `fs.list(path) -> s[], b` (entry names only, not full paths), `fs.mkdir(path) -> b`, `fs.remove(path) -> b`.
- `fs.err() -> s` is the detail layer under every `b`: the message from the last failed file operation, cleared by the next success. The habit it enables is `if not ok { panic(fs.err()) }`.

## 25. Generic constraints

```
fn biggest<T: ord>(T a, T b) -> T {
    if a > b { return a }
    return b
}

struct Buffer<T: num> {
    T[] data
    i count
}
```

- A constraint rides on the type parameter: `<T: ord>`, on functions, structs and methods alike. One constraint per parameter in v0.1.
- Two are built in: `num` (every `i*`, `u*`, `f*` — arithmetic and comparison) and `ord` (`<` `<=` `>` `>=` `==` — integers, floats, char, string).
- With a constraint, the body is checked **once, at the definition**, with the parameter named in any error (`T: ord does not support +`), and every instantiation is pre-checked against it. Without one, checking happens per instantiation (section 21) — loose but permissive.
- The stdlib uses them: `list.sort` is written `sort<T: ord>`, which is exactly why sort works on strings and fails on structs.
- User-defined constraints (traits) are not designed yet (section 27).

## 26. Concurrency

Baton's model is **tasks** — Luau's `task` library, not OS threads: cooperative, single-threaded, scheduled at explicit yield points.

```
fn fetch(s url) -> s {
    task.wait(200)                 -- pretend to load
    return "<html>...</html>"
}

fn main() -> i {
    Task local t = task.spawn(fetch("example.com"))
    print("loading...")
    s local page = task.join(t)    -- waits; other tasks keep running
    print(page)
    return 0
}
```

- `task.spawn(call)` starts a new task: the call is evaluated where you write it, its arguments are copied in, and the function runs cooperatively. No function values required — functions still are not values in baton. Returns a `Task` handle.
- A task runs until it finishes or hits a yield — `task.wait(i ms)` (where `wait(0)` yields immediately) or `task.join(Task)`. There is no preemption; ready tasks run in spawn order.
- `task.join(t) -> i` waits for the task and gives its `-> i` result (`0` for a void task). `task.stop(t)` cancels one that has not finished yet.
- The `Task` handle is opaque and refcounted like `File` — but dropping the handle does **not** cancel the task; handle lifetime and task lifetime are separate (`stop` is the cancel).
- Because everything shares one thread, there are no data races to worry about: globals are safe and reference counting stays non-atomic (section 13 is untouched).
- The bargain: one task that never yields blocks every other task, and blocking calls (`input()`, whole-file reads) pause all of them. Long loops take a `task.wait(0)`.
- When `main` returns, the scheduler drains — remaining tasks run to completion before the process exits. A task that never finishes keeps the program alive; `task.stop` it.
- OS threads and multicore parallelism are a different machine entirely — atomic refcounts and locking are undesigned (section 27).

## 27. Matrices

Matrices are multidimensional fixed arrays written with repeated brackets: `f[2][3]` is a 2 by 3 matrix of floats. They follow the same rules as arrays (section 12): fixed size, stack-allocated, copied by value.

```
f[2][3] local a = {{1.0, 2.0, 3.0}, {4.0, 5.0, 6.0}}
f[3][2] local b = {{7.0, 8.0}, {9.0, 10.0}, {11.0, 12.0}}
f[2][2] local c = a @ b
```

- **Literals** use nested braces: each row is `{...}` and rows are wrapped in another set of braces. Missing entries zero-initialize.
- **Indexing** works normally: `a[0][1]` accesses row 0, column 1.
- **Elementwise arithmetic** is supported for same-shaped numeric matrices: `a + b`, `a - b`. A matrix can be multiplied or divided by a numeric scalar: `a * 2.0`, `a / 2`.
- **Matrix multiplication** uses `@`: `a @ b` multiplies `m×n` by `n×p` to give `m×p`. Both operands must be 2-D numeric arrays with matching inner dimensions.
- **Slicing and lists** are separate features (sections 12, 14). Matrices are fixed arrays, not growable lists.
- **Type promotion** follows the normal numeric promotion rules (section 5).

## 28. Open questions

Not yet designed:

- **Parallelism:** OS threads and the atomic refcounts they need — tasks (section 26) cover scheduling, not multicore
- **User-defined constraints:** traits/interfaces, until `num` and `ord` prove too few
- **Async I/O:** blocking reads pause every task (sections 24, 26)
