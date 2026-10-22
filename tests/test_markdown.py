#!/usr/bin/env python3
"""Tests for the markdown renderer behind `baton man`.

Run with:

    python3 tests/test_markdown.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from baton.markdown import render


class RenderTest(unittest.TestCase):
    def test_heading_becomes_a_ruled_title(self):
        out = render("## 13. Memory management\n")
        title = "13. MEMORY MANAGEMENT"
        self.assertEqual(out, "%s\n%s\n" % (title, "-" * len(title)))

    def test_heading_levels_use_different_rules(self):
        out = render("# Title\n\n## Sub\n\n### Deep\n")
        self.assertIn("TITLE\n=====", out)
        self.assertIn("SUB\n---", out)
        self.assertIn("DEEP\n....", out)

    def test_code_block_is_left_alone(self):
        source = "```\nfn add(i a, i b) -> i {\n    return a + b\n}\n```\n"
        self.assertIn("fn add(i a, i b) -> i {", render(source))
        self.assertNotIn("```", render(source))

    def test_code_inside_a_code_block_keeps_its_stars(self):
        out = render("```\npower() { return a ** b }\n```\n")
        self.assertIn("a ** b", out)

    def test_table_becomes_aligned_columns(self):
        out = render("| Letter | Type |\n|---|---|\n| `i` | signed |\n")
        lines = out.split("\n")
        self.assertEqual(lines[0], "Letter  Type")
        self.assertEqual(lines[1], "------  ------")
        self.assertEqual(lines[2], "`i`     signed")

    def test_table_without_a_header_rule_keeps_its_rows(self):
        out = render("| a | b |\n| c | d |\n")
        self.assertIn("a  b", out)
        self.assertIn("c  d", out)

    def test_emphasis_markers_go_away(self):
        out = render("Strings are **immutable** and *shared*.\n")
        self.assertEqual(out, "Strings are immutable and shared.\n")

    def test_emphasis_may_span_a_code_span(self):
        out = render("Use **`clone()`** to copy.\n")
        self.assertEqual(out, "Use `clone()` to copy.\n")

    def test_a_star_in_a_code_span_is_not_emphasis(self):
        out = render("the same `T *` gcc uses\n")
        self.assertEqual(out, "the same `T *` gcc uses\n")

    def test_the_power_operator_survives(self):
        out = render("- `**` on ints compiles to a helper.\n")
        self.assertIn("`**` on ints", out)

    def test_links_keep_their_address(self):
        out = render("see [the spec](http://example.com) now\n")
        self.assertEqual(out, "see the spec (http://example.com) now\n")

    def test_horizontal_rules_are_dropped(self):
        out = render("## One\n\n---\n\n## Two\n")
        self.assertEqual(out, "ONE\n---\n\nTWO\n---\n")

    def test_prose_is_wrapped(self):
        out = render("word " * 40, width=40)
        for line in out.strip("\n").split("\n"):
            self.assertLessEqual(len(line), 40)

    def test_list_items_hang_under_their_marker(self):
        out = render("- a long item that has to wrap somewhere here\n", width=40)
        lines = out.split("\n")
        self.assertTrue(lines[0].startswith("- "))
        self.assertTrue(lines[1].startswith("  "))
        self.assertFalse(lines[1].startswith("- "))


if __name__ == "__main__":
    unittest.main()
