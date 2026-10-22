"""Access to the language specification, `baton-spec.md`.

The specification is the source of truth for the language. It lives at the
root of the checkout, next to this package, so it is looked up in a few
places; `BATON_SPEC` overrides the search and may name the file itself or
the directory holding it.
"""

import os
import re
import sys

SPEC_NAME = "baton-spec.md"

# Top-level sections look like "## 13. Memory management".
_HEADING = re.compile(r"^##[ \t]+(\d+)\.[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def _walk_up(start):
    """Yield `start` and every directory above it."""
    current = os.path.abspath(start)
    while True:
        yield current
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def _search_dirs():
    """Directories that may hold the specification."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    yield root  # checkout layout: <root>/baton-spec.md
    program = sys.argv[0] if sys.argv else ""
    if program:
        yield os.path.dirname(os.path.abspath(program))
    for directory in _walk_up(root):
        yield directory
    for directory in _walk_up(os.getcwd()):
        yield directory


def find_spec():
    """Locate the specification.

    Returns a `(path, problem)` pair: `path` is the specification file, or
    None when it cannot be found, and `problem` then says why.
    """
    override = os.environ.get("BATON_SPEC")
    if override:
        candidate = override
        if os.path.isdir(candidate):
            candidate = os.path.join(candidate, SPEC_NAME)
        if os.path.isfile(candidate):
            return candidate, None
        return None, "BATON_SPEC points at '%s', which is not a file" % override

    seen = set()
    for directory in _search_dirs():
        path = os.path.join(directory, SPEC_NAME)
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path, None
    return None, "no %s found" % SPEC_NAME


def read_spec(path):
    """Read the specification at `path`."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().replace("\r\n", "\n")


def sections(text):
    """Return the top-level sections of the spec.

    Each entry is a dict with `number`, `title`, `start` and `end`, the last
    two being character offsets into `text`.
    """
    matches = list(_HEADING.finditer(text))
    found = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found.append({
            "number": int(match.group(1)),
            "title": match.group(2),
            "start": start,
            "end": end,
        })
    return found


def match_sections(text, wanted):
    """Find sections by number or by (part of) their title.

    A number matches exactly. A title matches every section whose title
    contains it, so the caller can tell an ambiguous request from a miss.
    """
    found = sections(text)
    wanted = wanted.strip()
    if wanted.isdigit():
        number = int(wanted)
        return [s for s in found if s["number"] == number]

    needle = wanted.lower()
    return [s for s in found if needle in s["title"].lower()]


def find_section(text, wanted):
    """Find one section by number or title, or None when there is no match."""
    matches = match_sections(text, wanted)
    if len(matches) == 1:
        return matches[0]
    return None


def section_text(text, section):
    """The text of one section, heading included."""
    return text[section["start"]:section["end"]].strip("\n") + "\n"


def toc(text):
    """A listing of the spec's sections."""
    lines = ["Sections of the baton specification:", ""]
    for section in sections(text):
        lines.append("  %2d. %s" % (section["number"], section["title"]))
    lines.append("")
    return "\n".join(lines)
