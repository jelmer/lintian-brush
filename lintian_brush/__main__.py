#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij <jelmer@debian.org>
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

import argparse
import sys
from breezy.workingtree import WorkingTree
import locale
locale.setlocale(locale.LC_ALL, '')
# Use better default than ascii with posix filesystems that deal in bytes
# natively even when the C locale or no locale at all is given. Note that
# we need an immortal string for the hack, hence the lack of a hyphen.
sys._brz_default_fs_enc = "utf8"

import breezy  # noqa: E402
breezy.initialize()
import breezy.git  # noqa: E402
import breezy.bzr  # noqa: E402

from breezy.trace import note  # noqa: E402

from . import (  # noqa: E402
    NotDebianPackage,
    PendingChanges,
    available_lintian_fixers,
    find_fixers_dir,
    run_lintian_fixers,
    version_string,
    )


def main(argv):
    parser = argparse.ArgumentParser(prog='lintian-brush')
    parser.add_argument(
        '--no-update-changelog', action="store_true",
        help="do not update the changelog")
    parser.add_argument(
        '--version', action='version', version='%(prog)s ' + version_string)
    parser.add_argument(
        '--list-fixers', action="store_true", help="list available fixers")
    parser.add_argument(
        '--list-tags', action="store_true",
        help="list lintian tags for which fixers are available")
    parser.add_argument(
        '--fixers-dir', type=str, help='path to fixer scripts. [%(default)s]',
        default=find_fixers_dir())
    parser.add_argument(
        '--verbose', help='be verbose', action='store_true', default=False)
    parser.add_argument(
        '--directory', metavar='DIRECTORY', help='directory to run in',
        type=str, default='.')
    parser.add_argument(
        'fixers', metavar='FIXER', nargs='*',
        help='specific fixer to run')
    args = parser.parse_args(argv)

    if args.list_fixers and args.list_tags:
        parser.print_usage()
        return 1

    fixers = available_lintian_fixers(args.fixers_dir)
    if args.list_fixers:
        for script in sorted([fixer.script_path for fixer in fixers]):
            note(script)
    elif args.list_tags:
        tags = set()
        for fixer in fixers:
            tags.update(fixer.lintian_tags)
        for tag in sorted(tags):
            note(tag)
    else:
        wt = WorkingTree.open(args.directory)
        if args.fixers:
            fixers = [f for f in fixers if f.name in args.fixers]
        with wt.lock_write():
            try:
                applied = run_lintian_fixers(
                    wt, fixers,
                    update_changelog=(not args.no_update_changelog),
                    verbose=args.verbose)
            except NotDebianPackage:
                note("%s: Not a debian package.", wt.basedir)
                return 1
            except PendingChanges:
                note("%s: Please commit pending changes first.", wt.basedir)
                return 1
        if applied:
            all_tags = set()
            for tags, summary in applied:
                all_tags.update(tags)
            note("Lintian tags fixed: %r" % all_tags)
        else:
            note("No changes made.")


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
