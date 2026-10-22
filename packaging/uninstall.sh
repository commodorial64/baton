#!/bin/sh
# Runs before yapm removes the package.
#
# yapm deletes the package directory itself. This takes care of the two
# things the package put outside its own tree: the manual page, and the
# symlink in /usr/local/bin.

MANPAGE=/usr/share/man/man1/baton.1
LINK=/usr/local/bin/baton

if [ -f "$MANPAGE" ]; then
    rm -f "$MANPAGE"
    echo "baton: removed $MANPAGE"
fi

# only drop the symlink when it is the one this package made
if [ -L "$LINK" ]; then
    target=$(readlink -f "$LINK" 2>/dev/null)
    case "$target" in
        /var/lib/yapm/packages/baton-*)
            rm -f "$LINK"
            echo "baton: removed $LINK"
            ;;
    esac
fi
