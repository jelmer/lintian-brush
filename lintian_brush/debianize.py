#!/usr/bin/python3
# Copyright (C) 2020 Jelmer Vernooij
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

"""Debianize a package."""

from debian.changelog import Changelog, Version, get_maintainer, format_date
from debian.deb822 import Deb822
import os
import sys


def write_debhelper_rules_template(path):
    with open(path, 'w') as f:
        f.write("""\
#!/usr/bin/make -f

%:
\tdh $@
""")
    os.chmod(path, 0o755)


def write_control_template(path, source, binaries):
    with open('debian/control', 'wb') as f:
        source.dump(f)
        for binary in binaries:
            f.write(b'\n')
            binary.dump(f)


def write_changelog_template(path, source_name, version, itp_bug=None):
    if itp_bug:
        closes = ' Closes: #%d' % itp_bug
    else:
        closes = ''
    cl = Changelog()
    cl.new_block(
        package=source_name,
        version=version,
        distributions='UNRELEASED',
        urgency='low',
        changes=['', '  * Initial release.' + closes, ''],
        author='%s <%s>' % get_maintainer(),
        date=format_date())
    with open(path, 'w') as f:
        cl.write_to_open_file(f)


def main(argv=None):
    import argparse
    from breezy.workingtree import WorkingTree

    import breezy  # noqa: E402
    breezy.initialize()
    import breezy.git  # noqa: E402
    import breezy.bzr  # noqa: E402
    from breezy.plugins.debian.upstream.branch import upstream_branch_version
    from breezy import osutils
    from breezy.commit import NullCommitReporter

    from lintian_brush import (
        available_lintian_fixers,
        version_string,
        check_clean_tree,
        PendingChanges,
        get_dirty_tracker,
        run_lintian_fixers,
        get_committer,
        )
    from lintian_brush.debhelper import maximum_debhelper_compat_version
    from lintian_brush.upstream_metadata import guess_upstream_metadata
    from breezy.trace import note  # noqa: E402

    parser = argparse.ArgumentParser(prog='debianize')
    parser.add_argument(
        '--directory', metavar='DIRECTORY', help='directory to run in',
        type=str, default='.')
    parser.add_argument(
        '--disable-inotify', action='store_true', default=False,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--version', action='version', version='%(prog)s ' + version_string)
    parser.add_argument('--compat-release', type=str, help=argparse.SUPPRESS)
    parser.add_argument(
        '--verbose', help='be verbose', action='store_true', default=False)
    parser.add_argument(
        '--disable-net-access',
        help='Do not probe external services.',
        action='store_true', default=False)
    parser.add_argument(
        '--diligent', action='count', default=0, dest='diligence',
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--trust',
        action='store_true',
        help='Whether to allow running code from the package.')
    parser.add_argument(
        '--consult-external-directory',
        action='store_true',
        help='Pull in external (not maintained by upstream) directory data')
    parser.add_argument(
        '--check', action='store_true',
        help='Check guessed metadata against external sources.')

    minimum_certainty = 'possible'  # For now..

    args = parser.parse_args(argv)

    compat_release = args.compat_release
    if compat_release is None:
        import distro_info
        debian_info = distro_info.DebianDistroInfo()
        compat_release = debian_info.stable()

    wt, subpath = WorkingTree.open_containing(args.directory)

    use_inotify = (False if args.disable_inotify else None),
    try:
        check_clean_tree(wt)
    except PendingChanges:
        note("%s: Please commit pending changes first.", wt.basedir)
        return 1

    dirty_tracker = get_dirty_tracker(wt, subpath, use_inotify)
    if dirty_tracker:
        dirty_tracker.mark_clean()

    try:
        os.mkdir('debian')
    except FileExistsError:
        note('%s: A debian directory already exists.', wt.abspath(subpath))
        return 1

    metadata = guess_upstream_metadata(
        '.', args.trust, not args.disable_net_access,
        consult_external_directory=args.consult_external_directory,
        check=args.check)

    try:
        upstream_name = metadata['Name']
    except KeyError:
        note('%s: Unable to determine upstream package name.',
             wt.abspath(subpath))
        return 1

    # TODO(jelmer): Check that there are no unallowed characters in
    # upstream_name

    source_name = upstream_name

    upstream_version = upstream_branch_version(
        wt.branch, wt.last_revision(), source_name)

    version = Version(upstream_version + '-1')
    source = Deb822()
    source['Source'] = source_name
    # TODO(jelmer) Fill in binaries
    binaries = [Deb822({'Package': 'python-%s' % source_name})]
    source['Build-Depends'] = (
        'debhelper-compat (= %d)' % maximum_debhelper_compat_version(
            compat_release))

    try:
        write_debhelper_rules_template('debian/rules')
        write_control_template('debian/control', source, binaries)
        write_changelog_template('debian/changelog', source_name, version)

        initial_files = [
            osutils.pathjoin(subpath, p)
            for p in [
                'debian', 'debian/changelog', 'debian/control', 'debian/rules']]
        wt.add(initial_files)

        wt.commit(
            'Create debian/ directory', allow_pointless=False,
            committer=get_committer(wt),
            specific_files=initial_files,
            reporter=NullCommitReporter())
    except:
        reset_tree(wt, dirty_tracker, subpath)
        raise

    fixers = available_lintian_fixers()

    with wt.lock_write():
        run_lintian_fixers(
            wt, fixers,
            update_changelog=False,
            compat_release=compat_release,
            verbose=args.verbose,
            minimum_certainty=minimum_certainty,
            trust_package=args.trust,
            allow_reformatting=True,
            use_inotify=use_inotify,
            subpath=subpath,
            net_access=not args.disable_net_access,
            opinionated=True,
            diligence=args.diligence)


if __name__ == '__main__':
    sys.exit(main())