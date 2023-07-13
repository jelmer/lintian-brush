#!/usr/bin/python3
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

"""Support for accessing UDD."""

import os

DEFAULT_UDD_URL = (
    'postgresql://udd-mirror:udd-mirror@udd-mirror.debian.net:5432/udd')


_pool = None


def connect_udd_mirror():
    import psycopg2

    global _pool
    if not _pool:
        udd_url = os.environ.get('UDD_URL', DEFAULT_UDD_URL)
        _pool = psycopg2.connect(udd_url)
        _pool.set_client_encoding('UTF8')
    return _pool
