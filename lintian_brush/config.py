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

"""Lintian-brush configuration file."""

import os

from configobj import ConfigObj
import warnings
import distro_info


PACKAGE_CONFIG_FILENAME = "debian/lintian-brush.conf"


SUPPORTED_KEYS = [
    "compat-release",
    "minimum-certainty",
    "allow-reformatting",
    "update-changelog",
]


def resolve_release_codename(name: str, date=None) -> str:
    def oldest_name(fn):
        return max(fn("object", date), key=lambda r: r.created).name

    if '/' in name:
        distro, name = name.split('/', 1)
    else:
        distro = None
    if distro in ('debian', None):
        debian = distro_info.DebianDistroInfo()
        if name == 'lts':
            return oldest_name(debian.lts_supported)
        if name == 'elts':
            return oldest_name(debian.elts_supported)
        if debian.codename(name):
            return debian.codename(name)
        if debian.valid(name):
            return name
    if distro in ('ubuntu', None):
        ubuntu = distro_info.UbuntuDistroInfo()
        if name == 'esm':
            return oldest_name(ubuntu.supported_esm)
        if ubuntu.valid(name):
            return name
        return None


class Config(object):
    """A configuration file."""

    def __init__(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self._obj = ConfigObj(path, raise_errors=True, file_error=True)
        for k in self._obj.keys():
            if k not in SUPPORTED_KEYS:
                warnings.warn("unknown setting %s in %s" % (k, path))

    @classmethod
    def from_workingtree(cls, wt, subpath):
        return cls(os.path.join(wt.basedir, subpath, PACKAGE_CONFIG_FILENAME))

    def compat_release(self):
        value = self._obj.get("compat-release")
        codename = resolve_release_codename(value)
        if codename is None:
            warnings.warn("unknown compat release %s, ignoring." % value)
        return codename

    def allow_reformatting(self):
        try:
            return self._obj.as_bool("allow-reformatting")
        except KeyError:
            return None

    def minimum_certainty(self):
        return self._obj.get("minimum-certainty")

    def update_changelog(self):
        try:
            return self._obj.as_bool("update-changelog")
        except KeyError:
            return None
