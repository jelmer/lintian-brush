#!/usr/bin/python3
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

"""Utility functions for dealing with copyright files."""

__all__ = [
    'NotMachineReadableError',
    'MachineReadableFormatError',
    'CopyrightEditor',
    ]

from debian.copyright import (
    Copyright,
    MachineReadableFormatError,
    NotMachineReadableError,
    )

from .reformatting import Editor


class CopyrightEditor(Editor):
    """Update a machine-readable copyright file.
    """

    def __init__(self, path='debian/copyright'):
        super(CopyrightEditor, self).__init__(path)

    def _parse(self, content):
        return Copyright(content, strict=False)

    def _format(self, parsed):
        return parsed.dump()

    @property
    def copyright(self):
        return self._parsed


def upstream_fields_in_copyright(path='debian/copyright'):
    ret = {}
    try:
        with open(path, 'r') as f:
            c = Copyright(f, strict=False)
    except (FileNotFoundError, NotMachineReadableError,
            MachineReadableFormatError):
        return {}
    else:
        if c.header.upstream_contact:
            ret['Contact'] = c.header.upstream_contact
        if c.header.upstream_name:
            ret['Name'] = c.header.upstream_name
    return ret
