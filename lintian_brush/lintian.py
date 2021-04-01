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

import os
from typing import Optional

LINTIAN_DATA_PATH = '/usr/share/lintian/data'


def read_debhelper_lintian_data_file(f, sep):
    for line in f:
        if line.startswith("#"):
            continue
        if not line.strip():
            continue
        line = line.rstrip("\n")
        try:
            key, value = line.split(sep, 1)
        except ValueError:
            key = line
            value = None
        yield key, value


def read_list_file(f, vendor):
    for line in f:
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        if line.startswith('@'):
            cond, if_vendor, val = line.split(None, 2)
            if cond == '@if-vendor-is-not':
                if if_vendor.lower() == vendor.lower():
                    continue
                line = val
            else:
                raise ValueError('invalid check %r' % cond)
        yield line


OBSOLETE_SITES_PATH = os.path.join(LINTIAN_DATA_PATH, 'obsolete-sites/obsolete-sites')
_obsolete_sites = None


def is_obsolete_site(parsed_url) -> Optional[str]:
    global _obsolete_sites
    if _obsolete_sites is None:
        with open(OBSOLETE_SITES_PATH, 'r') as f:
            _obsolete_sites = list(read_list_file(f, vendor=None))
    for site in _obsolete_sites:
        if parsed_url.hostname.endswith(site):
            return site
    else:
        return None


KNOWN_TESTS_CONTROL_FIELDS_PATH = os.path.join(
    LINTIAN_DATA_PATH, 'testsuite/known-fields')


def _capitalize_field(field):
    return "-".join([x.capitalize() for x in field.split("-")])


def _read_test_fields(path, vendor):
    with open(path, 'r') as f:
        fields = list(read_list_file(f, vendor=vendor))

    # Older versions of lintian listed fields with all lowercase.
    if all([x == x.lower() for x in fields]):
        fields = set([_capitalize_field(x) for x in fields])
    return fields


def known_tests_control_fields(vendor):
    return _read_test_fields(KNOWN_TESTS_CONTROL_FIELDS_PATH, vendor)


KNOWN_SOURCE_FIELDS_PATH = os.path.join(
    LINTIAN_DATA_PATH, 'common/source-fields')


def known_source_fields(vendor):
    return _read_test_fields(KNOWN_SOURCE_FIELDS_PATH, vendor)


KNOWN_BINARY_FIELDS_PATH = os.path.join(
    LINTIAN_DATA_PATH, 'fields/binary-fields')


def known_binary_fields(vendor):
    return _read_test_fields(KNOWN_BINARY_FIELDS_PATH, vendor)


DEBHELPER_DH_COMMANDS_PATH = os.path.join(
    LINTIAN_DATA_PATH, 'debhelper/dh_commands')


def dh_commands():
    with open(DEBHELPER_DH_COMMANDS_PATH, 'r') as f:
        return list(read_debhelper_lintian_data_file(f, '='))
