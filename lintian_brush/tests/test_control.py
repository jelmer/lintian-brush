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

"""Tests for lintian_brush.control."""

from breezy.tests import (
    TestCase,
    TestCaseWithTransport,
    )

from lintian_brush.control import (
    can_preserve_deb822,
    ensure_minimum_version,
    update_control,
    GeneratedFile,
    FormattingUnpreservable,
    PkgRelation,
    format_relations,
    parse_relations,
    )


class CanPreserveDeb822Tests(TestCase):

    def test_comment(self):
        self.assertFalse(can_preserve_deb822(b"""\
Source: blah
# A comment
Testsuite: autopkgtest

"""))

    def test_fine(self):
        self.assertTrue(can_preserve_deb822(b"""\
Source: blah
Testsuite: autopkgtest

"""))


class UpdateControlTests(TestCaseWithTransport):

    def test_do_not_edit(self):
        self.build_tree_contents([('debian/', ), ('debian/control', """\
# DO NOT EDIT
# This file was generated by blah

Source: blah
Testsuite: autopkgtest

""")])
        self.assertRaises(GeneratedFile, update_control)

    def test_unpreservable(self):
        self.build_tree_contents([('debian/', ), ('debian/control', """\
Source: blah
# A comment
Testsuite: autopkgtest

""")])
        self.assertRaises(FormattingUnpreservable, update_control)

    def test_modify_source(self):
        self.build_tree_contents([('debian/', ), ('debian/control', """\
Source: blah
Testsuite: autopkgtest

""")])

        def add_header(control):
            control["XS-Vcs-Git"] = "git://github.com/example/example"
        update_control(source_package_cb=add_header)
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest
XS-Vcs-Git: git://github.com/example/example
""", 'debian/control')

    def test_modify_binary(self):
        self.build_tree_contents([('debian/', ), ('debian/control', """\
Source: blah
Testsuite: autopkgtest

Package: libblah
Section: extra

""")])

        def add_header(control):
            control["Arch"] = "all"
        update_control(binary_package_cb=add_header)
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest

Package: libblah
Section: extra
Arch: all
""", 'debian/control')

    def test_doesnt_strip_whitespace(self):
        self.build_tree_contents([('debian/', ), ('debian/control', """\
Source: blah
Testsuite: autopkgtest

""")])
        update_control()
        self.assertFileEqual("""\
Source: blah
Testsuite: autopkgtest

""", 'debian/control')


class ParseRelationsTests(TestCase):

    def test_empty(self):
        self.assertEqual([], parse_relations(''))
        self.assertEqual([('\n', [], '')], parse_relations('\n'))

    def test_simple(self):
        self.assertEqual(
                [('', [PkgRelation('debhelper')], '')],
                parse_relations('debhelper'))
        self.assertEqual(
                [('  \n', [PkgRelation('debhelper')], '')],
                parse_relations('  \ndebhelper'))
        self.assertEqual(
                [('  \n', [PkgRelation('debhelper')], ' \n')],
                parse_relations('  \ndebhelper \n'))


class FormatRelationsTests(TestCase):

    def test_empty(self):
        self.assertEqual(
                '',
                format_relations([('', [], '')]))
        self.assertEqual(
                '\n',
                format_relations([('', [], '\n')]))

    def test_simple(self):
        self.assertEqual(
                'debhelper',
                format_relations([('', [PkgRelation('debhelper')], '')]))
        self.assertEqual(
                format_relations([('  \n', [PkgRelation('debhelper')], '')]),
                '  \ndebhelper')
        self.assertEqual(
                format_relations(
                    [('  \n', [PkgRelation('debhelper')], ' \n')]),
                '  \ndebhelper \n')

    def test_multiple(self):
        self.assertEqual(
                'debhelper, blah',
                format_relations([('', [PkgRelation('debhelper')], ''),
                                 (' ', [PkgRelation('blah')], '')]))


class EnsureMinimumVersionTests(TestCase):

    def test_added(self):
        self.assertEqual(
            'debhelper (>= 9)', ensure_minimum_version('', 'debhelper', '9'))
        self.assertEqual(
            'blah, debhelper (>= 9)',
            ensure_minimum_version('blah', 'debhelper', '9'))

    def test_updated(self):
        self.assertEqual(
            'debhelper (>= 9)',
            ensure_minimum_version('debhelper', 'debhelper', '9'))
        self.assertEqual(
            'blah, debhelper (>= 9)',
            ensure_minimum_version('blah, debhelper', 'debhelper', '9'))
        self.assertEqual(
            'blah, debhelper (>= 9)',
            ensure_minimum_version('blah, debhelper (>= 8)', 'debhelper', '9'))
