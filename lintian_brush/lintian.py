#!/usr/bin/python3
# Copyright (C) 2020 Jelmer Vernooij <jelmer@debian.org>
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

"""Functions for working with lintian data."""


def read_debhelper_lintian_data_file(f, sep):
    ret = {}
    for line in f:
        if line.startswith('#'):
            continue
        if not line.strip():
            continue
        key, value = line.rstrip('\n').split(sep, 1)
        ret[key] = value
    return ret