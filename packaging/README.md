# The yapm package

`yapm build` turns one directory into a `.yapm` archive, and it needs that
directory to hold a `yapm.data` plus everything the package installs. For
baton that is more than this directory: the compiler, the specification and
the examples all live in the repository above.

So the package is staged first, then built:

```
cd ~/Projects/baton
python3 packaging/build.py
```

which stages `dist/baton-<version>/` and runs `yapm build` on it, giving
`dist/baton-<version>.yapm`.

## What is staged

```
dist/baton-<version>/
  yapm.data         the manifest, from packaging/yapm.data
  run/baton         the launcher, from packaging/run/baton
  lib/baton/        the compiler, copied from baton/
  share/baton/      baton-spec.md and the examples, from the repository
  man/baton.1       the manual page, from packaging/man/baton.1
  uninstall.sh      from packaging/uninstall.sh
```

The version comes from `baton/__init__.py`, so it never drifts from what
`baton --version` reports.

## Do not do this

```
sudo yapm build ~/Projects/baton     # no yapm.data in the repository root
sudo yapm build packaging            # builds a package with no compiler in it
```

Both make a `.yapm` that cannot work: the first has no manifest, the second
has a manifest but no `lib/baton` to import.

## Installing

```
sudo yapm install dist/baton-<version>.yapm
```

That links `/usr/local/bin/baton` and installs the manual page in
`/usr/share/man/man1`. `sudo yapm remove baton-<version>` takes it away
again.
