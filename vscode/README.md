# Baton for Visual Studio Code

Language support for Baton, the statically typed language that compiles to C.
The extension covers `.bt` files and works on its own; the compiler is only
needed for diagnostics.

## Features

- **Syntax highlighting** for keywords, types, declarations, calls, strings,
  comments, numbers and namespace members.
- **IntelliSense** for keywords, types, `local`/`const`/`global` declarations,
  functions, parameters, structs, namespaces and imported modules. Locals and
  parameters are offered only where they are in scope.
- **Hover** for language words, the standard namespaces (`str`, `math`, `list`,
  `rand`, `time`, `fs`, `task`) and `File` methods, with signatures and short
  descriptions from the specification.
- **Signature help** while typing a call, including overloads and the active
  parameter.
- **Document outline** (Go to Symbol / breadcrumbs) for functions, structs,
  namespaces, globals and imported modules.
- **Snippets** for the common declarations and control-flow forms.
- **Diagnostics** from `baton check`, with the compiler's errors and warnings
  shown on the matching source line.

## Installing

The quickest route from a checkout is to package the extension and install the
resulting VSIX:

```
cd vscode
npm run package
code --install-extension baton-0.1.1.vsix
```

For development, open the `vscode` directory in VS Code and press `F5` to start
an Extension Development Host with the extension loaded.

## Compiler

Diagnostics need a working Baton compiler. The extension looks for one in this
order:

1. The `baton.executable` setting (for example `python3 -m baton`).
2. `python3 -m baton` in the workspace root, when `baton/__init__.py` is there.
3. `bin/baton` in the workspace root.
4. `python3 -m baton` run from the directory of the file being edited.

If none is found, a notification offers to open the setting. Highlighting,
completion and the other editor features do not need the compiler.

`baton check` writes a `.c` file beside its input, so the extension checks a
temporary copy of the document. Nothing is written next to your sources.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `baton.executable` | `baton` | Command used to run the compiler, for example `baton` or `python3 -m baton`. When it is left at the default and `baton` is not installed, the workspace copy is used automatically. |
| `baton.diagnostics.run` | `onSave` | When to run `baton check`: `onSave`, `onType` or `off`. |

`Baton: Check Current File` in the command palette runs a check immediately
regardless of the setting.

## Tests

The extension has no runtime dependencies and no build step. The providers are
kept separate from the VS Code API where possible so the analysis can be
tested directly:

```
cd vscode
npm test
```

## Limitations

The analyzer is a lightweight scanner rather than a second implementation of
the type checker. It resolves names by block scope and infers types from
declarations and obvious initializers; complex expressions fall back to the
declared type or no type at all. Diagnostics come from the real compiler and
are therefore bound by what this build of Baton implements.
