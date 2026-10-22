"""Markdown rendered for the terminal.

`baton man` reads baton-spec.md, which is Markdown. Handing Markdown to a
terminal leaves the reader looking at `##`, `**` and pipe tables, so the
document is rendered to plain text first: headings become ruled titles,
tables become aligned columns, and the emphasis markers go away. Code
blocks are left exactly as written, because they are code.
"""

import re
import textwrap

# a rule under the title, troff style
RULES = {1: "=", 2: "-", 3: "."}

_FENCE = "```"
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_SEPARATOR = re.compile(r"^:?-{2,}:?$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _emphasis(text):
    """Drop the emphasis markers, keep the words."""
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = _LINK.sub(r"\1 (\2)", text)
    return text


def _inline(text):
    """Resolve the inline markup of one piece of prose.

    Code spans are set aside first, so a `*` inside one is never mistaken
    for emphasis, and so emphasis may still span a code span — the
    specification writes things like **`clone()`**. The backticks stay: they
    are what tells the reader that a word is code and not prose.
    """
    spans = []

    def stash(match):
        spans.append(match.group(1))
        return "\x00%d\x00" % (len(spans) - 1)

    text = re.sub(r"(`[^`]+`)", stash, text)
    text = _emphasis(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def _row(cells, widths):
    padded = [cell.ljust(width) for cell, width in zip(cells, widths)]
    return "  ".join(padded).rstrip()


def _table(rows):
    """Render a pipe table as aligned columns."""
    parsed = []
    for row in rows:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        parsed.append([_inline(cell.strip()) for cell in row.split("|")])

    header = None
    body = parsed
    if len(parsed) > 1 and all(_SEPARATOR.match(cell) for cell in parsed[1]):
        header = parsed[0]
        body = parsed[2:]

    columns = max([len(row) for row in body] + [len(header) if header else 0])
    widths = [0] * columns
    for row in ([header] if header else []) + body:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    lines = []
    if header:
        lines.append(_row(header, widths))
        lines.append("  ".join("-" * width for width in widths))
    for row in body:
        lines.append(_row(row, widths))
    return lines


def _starts_block(line):
    stripped = line.strip()
    return (stripped.startswith(_FENCE) or _HEADING.match(stripped)
            or _RULE.match(line) or _LIST.match(line)
            or stripped.startswith("|"))


def _blank(out):
    """Start a new block, unless one is already separated."""
    if out and out[-1].strip():
        out.append("")


def render(markdown, width=80):
    """Render Markdown as plain text for a terminal."""
    lines = markdown.split("\n")
    out = []
    index = 0

    while index < len(lines):
        line = lines[index]

        # a fenced code block: the code as written, without the fences
        if line.strip().startswith(_FENCE):
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(_FENCE):
                out.append(lines[index])
                index += 1
            index += 1
            out.append("")
            continue

        # a pipe table
        if line.strip().startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index])
                index += 1
            _blank(out)
            out.extend(_table(rows))
            out.append("")
            continue

        # a heading
        heading = _HEADING.match(line.strip())
        if heading:
            level = len(heading.group(1))
            title = _inline(heading.group(2)).strip().rstrip("#").strip()
            out.append("")
            out.append(title.upper())
            out.append(RULES[min(level, 3)] * max(len(title), 3))
            out.append("")
            index += 1
            continue

        # a horizontal rule: the headings already separate the sections
        if _RULE.match(line):
            index += 1
            continue

        # a list item
        item = _LIST.match(line)
        if item:
            indent, marker, body = item.groups()
            prefix = indent + marker + " "
            wrapped = textwrap.wrap(_inline(body), width=max(width - len(prefix), 20),
                                    break_long_words=False, break_on_hyphens=False)
            if not wrapped:
                wrapped = [""]
            out.append(prefix + wrapped[0])
            for extra in wrapped[1:]:
                out.append(" " * len(prefix) + extra)
            index += 1
            continue

        # a blank line
        if not line.strip():
            index += 1
            continue

        # a paragraph
        paragraph = []
        while index < len(lines) and lines[index].strip() and not _starts_block(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        text = _inline(" ".join(paragraph))
        _blank(out)
        out.extend(textwrap.wrap(text, width=width, break_long_words=False,
                                 break_on_hyphens=False))
        out.append("")

    return re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip("\n")) + "\n"
