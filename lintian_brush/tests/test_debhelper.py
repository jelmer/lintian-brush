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

"""Tests for lintian_brush.debhelper."""

from breezy.tests import (
    TestCase,
    )

from ..debhelper import (
    lowest_non_deprecated_compat_level,
    highest_stable_compat_level,
    )


class LowestNonDeprecatedCompatLevel(TestCase):

    def test_is_valid(self):
        self.assertIsInstance(lowest_non_deprecated_compat_level(), int)


class HighestStableCompatLevelTests(TestCase):

    def test_is_valid(self):
        self.assertIsInstance(highest_stable_compat_level(), int)
