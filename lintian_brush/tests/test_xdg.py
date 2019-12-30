#!/usr/bin/python
# Copyright (C) 2019 Jelmer Vernooij
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

"""Tests for lintian_brush.xdg."""

from ..xdg import (
    DesktopEntryUpdater,
    )

from breezy.tests import (
    TestCaseWithTransport,
    )


class UpdateDesktopEntryTests(TestCaseWithTransport):

    def test_weird_spacing(self):
        self.build_tree_contents([('foo.desktop', """\
[Desktop Entry]
Name= foo
""")])
        with DesktopEntryUpdater('foo.desktop') as updater:
            updater['NewField'] = 'foo'
        self.assertFileEqual("""\
[Desktop Entry]
Name= foo
NewField=foo
""", 'foo.desktop')

    def test_modify(self):
        self.build_tree_contents([('foo.desktop', """\
[Desktop Entry]
Name=Foo
""")])
        with DesktopEntryUpdater('foo.desktop') as updater:
            updater['NewField'] = 'foo'

        self.assertFileEqual("""\
[Desktop Entry]
Name=Foo
NewField=foo
""", 'foo.desktop')
