# baton

A statically typed, general-purpose, low-level language that compiles to C and is
built with gcc. Lua-flavored declarations, single-letter type prefixes,
brace-delimited blocks, compiler-managed memory.

The language definition lives in [`baton-spec.md`](baton-spec.md). That document
is the source of truth; this directory is the compiler that implements it.

## Usage

```
python3 -m baton build examples/hello.bt      # -> hello.c, then gcc -> ./hello
python3 -m baton run   examples/hello.bt      # build and run
python3 -m baton build examples/hello.bt -o hello -W error
python3 -m baton man                          # read the language specification
```

`bin/baton` is a shim, so `./bin/baton build hello.bt` works too.

Options:

- `-o FILE` — output binary path (default: source name without `.bt`)
- `-W none` — silence warnings
- `-W error` — promote warnings to errors
- `--emit-c` — write the C and stop, no gcc

## Editor support

The [`vscode/`](vscode/) directory contains a Visual Studio Code extension for
`.bt` files: syntax highlighting, completion and hover for declarations and the
standard namespaces, signature help, an outline, snippets, and diagnostics from
`baton check`. It has no build step and no runtime dependencies.

```
cd vscode
npm run package
code --install-extension baton-0.1.1.vsix
```

The extension finds the compiler from the `baton.executable` setting or from
the open workspace (`python3 -m baton` or `bin/baton`), so a checkout works
without installing Baton first. Checks run on save by default; set
`baton.diagnostics.run` to `onType` or `off` to change that. See
[`vscode/README.md`](vscode/README.md) for the details.

## The specification

`baton man` prints `baton-spec.md`, the document the language is defined in.
The specification is written in Markdown, but it is rendered as plain text
for the terminal: headings become ruled titles and tables become aligned
columns. It goes through a pager when the output is a terminal, so it can be
read comfortably; piped or redirected, it writes the text straight out.

```
python3 -m baton man              # the whole specification
python3 -m baton man 13           # section 13, Memory management
python3 -m baton man memory       # the section whose title matches
python3 -m baton man --list       # list the sections
python3 -m baton man --raw        # the markdown itself
python3 -m baton man --no-pager   # do not use a pager
```

The spec file is found next to the `baton` package, or wherever the current
directory leads. Set `BATON_SPEC` to point at it explicitly.

## What this build implements

The pipeline of spec section 1: `lexer -> parser -> type checker -> C codegen ->
gcc`. Implemented today:

- **Lexical** (spec 2): `--` and `-/ -/` comments, identifiers, all keywords,
  integer literals in dec/hex/oct/bin with `_` separators, floats, strings, chars,
  the escapes `\n \t \r \\ \" \' \0 \xHH`.
- **Variables** (spec 3): `local` / `const`, optional type prefix with the
  inference warning exactly as specified, zero-init, multiple declaration and
  multiple assignment (`a, b = b, a`), block scoping, shadowing, globals
  (including the hoisted `bt_init()` for non-constant global initializers).
- **Types** (spec 4): `i i8 i16 i32 i64 u u8 u16 u32 u64 f f32 b c s`. No
  truthiness — conditions must be `b`.
- **Conversions** (spec 5): the widening rules, literal adaptation with range
  checking (`u8 local d = 256` is an error), mixed signed/unsigned error, `as`,
  and `toi` / `tof` / `tos` / `tob`.
- **Strings** (spec 6): content comparison and ordering, `+` joins.
- **Operators** (spec 7): the full set with the spec's precedence table (bitwise
  tighter than comparison, `**` above unary, right-associative), integer division
  truncating toward zero, `**` via a generated helper.
- **Functions** (spec 8): parameters, `->` return type, `return`, `main` as entry
  point with its return value as the exit code, overload selection on parameter
  types, prototype-before-use.
- **Control flow** (spec 10): `if` / `elf` / `else`, `while`, `loop`, `for` ranges
  with `..` `..=` and `by` (negative steps count down), `break` / `continue`, and
  loop labels (`outer:` with `break outer` / `continue outer`).
- **I/O and errors** (specs 17, 18): `print` (spaces between values, floats at
  full precision), `write`, `input`, `panic` with a source line, division-by-zero
  as a runtime error with a source line.

Everything else in the spec — structs, arrays and lists, reference counting,
methods, `match`, namespaces, modules and `expose`, pointers, generics, multiple
return values, `extern fn`, the `str`/`math`/`list`/`rand`/`time`/`fs`/`task`
namespaces — is **not in this build yet**. Where the parser meets one of those
constructs it stops with a message naming the construct, rather than
miscompiling it.

## Tests

```
python3 tests/run_tests.py
```

Each case is a `.bt` file in `tests/` with a companion file that says what to
expect:

- `<name>.expect` — build and run, stdout must match exactly
- `<name>.in` — stdin fed to the run above
- `<name>.exit` — the exit code the run must return
- `<name>.err` — the program must fail to compile, and every listed line must
  appear in the diagnostics
- `<name>.warn` — the program must compile with the listed warnings, and `-W none`
  must silence them

## Packaging

The language ships as a [yapm](https://github.com/commodorial64/yapm) package.
`packaging/` holds the parts that are yapm-specific: the manifest, the
launcher that ends up in `/usr/local/bin`, the manual page and the uninstall
script.

```
cd ~/Projects/baton
python3 packaging/build.py                        # -> dist/baton-0.1.1.yapm
sudo yapm install dist/baton-0.1.1.yapm
```

`yapm build` on its own does not work here: it needs the manifest *and* the
files that go with it, so the tree is staged first and `yapm build` is run
on the staged copy. See [`packaging/README.md`](packaging/README.md).

The build script reads the version from `baton/__init__.py` and stages:

```
dist/baton-<version>/
  yapm.data         the manifest
  run/baton         the launcher, linked into /usr/local/bin
  lib/baton/        the compiler
  share/baton/      the specification and the sample programs
  man/baton.1       the manual page
  uninstall.sh      removes what the package put outside its own tree
```

The installed package puts `baton` on the PATH and the manual page in
`/usr/share/man/man1`, so `man baton` and `baton man` both work.
`sudo yapm remove baton-<version>` takes it all away again.

## Layout

```
baton/            the compiler package
  lexer.py        source -> tokens
  parser.py       tokens -> AST
  checker.py      types, scoping, warnings
  codegen.py      AST -> C
  runtime.py      the C runtime emitted into every program
  cli.py          baton build / run / check / man
  diagnostics.py  error and warning formatting
  spec.py         finding and sectioning baton-spec.md
  markdown.py     rendering the spec for the terminal
  types.py        the type model and the conversion rules
examples/         sample .bt programs
tests/            compiler test cases and the runner
bin/baton         shim so ./bin/baton works from a checkout
vscode/           the VS Code extension: grammar, providers, diagnostics
packaging/        the yapm package: manifest, launcher, man page
```

## License

MIT. See [`LICENSE`](LICENSE).
# baton
