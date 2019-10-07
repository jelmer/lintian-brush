#!/usr/bin/python
# Copyright (C) 2018 Jelmer Vernooij
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for lintian_brush.deb822."""

from breezy.tests import (
    TestCase,
    TestCaseWithTransport,
    )

from debian.deb822 import Deb822

from lintian_brush.deb822 import (
    dump_paragraphs,
    reformat_deb822,
    update_deb822,
    )
from lintian_brush.reformatting import (
    FormattingUnpreservable,
    GeneratedFile,
    )


class ReformatDeb822Tests(TestCase):

    def test_comment(self):
        self.assertEqual(reformat_deb822(b"""\
Source: blah
# A comment
Testsuite: autopkgtest

"""), b"""\
Source: blah
Testsuite: autopkgtest
""")

    def test_fine(self):
        self.assertTrue(reformat_deb822(b"""\
Source: blah
Testsuite: autopkgtest

"""), b"""\
Source: blah
Testsuite: autogpktest

""")


class DumpParagraphsTests(TestCase):

    def test_simple(self):
        self.assertEqual(dump_paragraphs([Deb822({
                'Source': 'blah',
                'Testsuite': 'autopkgtest'
            })]), b"""\
Source: blah
Testsuite: autopkgtest
""")

    def test_multi(self):
        self.assertEqual(dump_paragraphs([
            Deb822({
                'Source': 'blah',
                'Testsuite': 'autopkgtest'
            }),
            Deb822({'Package': 'bloe'})]), b"""\
Source: blah
Testsuite: autopkgtest

Package: bloe
""")


class UpdateControlTests(TestCaseWithTransport):

    def test_do_not_edit(self):
        self.build_tree_contents([('controlfile', """\
# DO NOT EDIT
# This file was generated by blah

Source: blah
Testsuite: autopkgtest

""")])

        def cb(c):
            c['Source'] = 'blah1'
        self.assertRaises(
            GeneratedFile, update_deb822, 'controlfile', paragraph_cb=cb)

    def test_do_not_edit_force(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
Testsuite: autopkgtest

"""), ('controlfile.in', 'bar')])

        def cb(c):
            c['Source'] = 'blah1'
        update_deb822('controlfile', paragraph_cb=cb, allow_generated=True)

    def test_do_not_edit_no_change(self):
        self.build_tree_contents([('controlfile', """\
# DO NOT EDIT
# This file was generated by blah

Source: blah
Testsuite: autopkgtest

""")])
        update_deb822('controlfile')

    def test_unpreservable(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
# A comment
Testsuite: autopkgtest

""")])

        def update_source(control):
            control["NewField"] = "New Field"
        self.assertRaises(
            FormattingUnpreservable, update_deb822,
            'controlfile', paragraph_cb=update_source)

    def test_modify_paragraph(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
Testsuite: autopkgtest

""")])

        def add_header(control):
            control["XS-Vcs-Git"] = "git://github.com/example/example"
        self.assertTrue(update_deb822(
            'controlfile', paragraph_cb=add_header))
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest
XS-Vcs-Git: git://github.com/example/example
""", 'controlfile')

    def test_doesnt_strip_whitespace(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
Testsuite: autopkgtest

""")])
        self.assertFalse(update_deb822('controlfile'))
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest

""", 'controlfile')
