#!/usr/bin/python
# Copyright (C) 2018 Jelmer Vernooij
# This file ias a part of lintian-brush.
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

from ..deb822 import (
    ChangeConflict,
    Deb822Updater,
    dump_paragraphs,
    reformat_deb822,
    )
from ..reformatting import (
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

        def change():
            with Deb822Updater('controlfile') as updater:
                for c in updater.paragraphs:
                    c['Source'] = 'blah1'
        self.assertRaises(GeneratedFile, change)

    def test_do_not_edit_force(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
Testsuite: autopkgtest

"""), ('controlfile.in', 'bar')])

        with Deb822Updater('controlfile', allow_generated=True) as updater:
            for c in updater.paragraphs:
                c['Source'] = 'blah1'

    def test_do_not_edit_no_change(self):
        self.build_tree_contents([('controlfile', """\
# DO NOT EDIT
# This file was generated by blah

Source: blah
Testsuite: autopkgtest

""")])
        with Deb822Updater('controlfile'):
            pass

    def test_unpreservable(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
# A comment
Testsuite: autopkgtest

""")])

        def change():
            with Deb822Updater('controlfile') as updater:
                for control in updater.paragraphs:
                    control["NewField"] = "New Field"

        self.assertRaises(FormattingUnpreservable, change)

    def test_modify_paragraph(self):
        self.build_tree_contents([('controlfile', """\
Source: blah
Testsuite: autopkgtest

""")])

        with Deb822Updater('controlfile') as updater:
            for control in updater.paragraphs:
                control["XS-Vcs-Git"] = "git://github.com/example/example"
        self.assertTrue(updater.changed)
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
        with Deb822Updater('controlfile') as updater:
            pass
        self.assertFalse(updater.changed)
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest

""", 'controlfile')


class ApplyChangesTests(TestCaseWithTransport):

    def setUp(self):
        super(ApplyChangesTests, self).setUp()
        self.build_tree_contents([('controlfile', """\
Source: blah
Testsuite: autopkgtest

""")])

    def test_simple_set(self):
        with Deb822Updater('controlfile') as updater:
            updater.apply_changes(
                {('Source', 'blah'): [('Build-Depends', None, 'foo')]})
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest
Build-Depends: foo
""", 'controlfile')

    def test_simple_change(self):
        with Deb822Updater('controlfile') as updater:
            updater.apply_changes(
                {('Source', 'blah'): [('Testsuite', 'autopkgtest', 'foo')]})
        self.assertFileEqual("""\
Source: blah
Testsuite: foo
""", 'controlfile')

    def test_change_conflict(self):
        with Deb822Updater('controlfile') as updater:
            self.assertRaises(
                ChangeConflict, updater.apply_changes,
                {('Source', 'blah'): [('Testsuite', 'different', 'foo')]})

    def test_simple_delete(self):
        with Deb822Updater('controlfile') as updater:
            updater.apply_changes(
                {('Source', 'blah'): [('Testsuite', 'autopkgtest', None)]})
        self.assertFileEqual("""\
Source: blah
""", 'controlfile')

    def test_delete_conflict(self):
        with Deb822Updater('controlfile') as updater:
            self.assertRaises(
                ChangeConflict, updater.apply_changes,
                {('Source', 'blah'): [('Nonexistent', 'autopkgtest', None)]})

    def test_simple_add_para(self):
        with Deb822Updater('controlfile') as updater:
            updater.apply_changes(
                {('Source', 'new'): [
                    ('Source', None, 'new'),
                    ('Build-Depends', None, 'bar')]})
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest

Source: new
Build-Depends: bar
""", 'controlfile')

    def test_simple_add_para_conflict(self):
        with Deb822Updater('controlfile') as updater:
            self.assertRaises(
                ChangeConflict,
                updater.apply_changes,
                {('Source', 'new'): [
                    ('Source', None, 'new'),
                    ('Build-Depends', 'bar', 'bar')]})