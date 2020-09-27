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

"""Utility for dropping unnecessary constraints."""

import asyncio
import os

from breezy.trace import note

try:
    from debmutate.debhelper import MaintscriptEditor
except ImportError:
    MaintscriptEditor = None


from debian.changelog import Version

from debmutate.control import (
    ControlEditor,
    parse_relations,
    format_relations,
    )

from .changelog import add_changelog_entry


_changelog_policy_noted = False


def _note_changelog_policy(policy, msg):
    global _changelog_policy_noted
    if not _changelog_policy_noted:
        if policy:
            extra = 'Specify --no-update-changelog to override.'
        else:
            extra = 'Specify --update-changelog to override.'
        note('%s %s', msg, extra)
    _changelog_policy_noted = True


def drop_old_maintscript(editor, package_name, upgrade_release):
    remove = []
    for i, entry in enumerate(list(editor.lines)):
        if isinstance(entry, str):
            continue
        prior_version = getattr(entry, 'prior_version', None)
        if prior_version is None:
            continue
        package = entry.package or package_name
        compat_version = package_version(package, upgrade_release)
        if compat_version is None:
            continue
        if compat_version > prior_version:
            remove.append(i)
    removed = []
    for i in reversed(remove):
        removed.append(editor.lines[i])
        del editor.lines[i]
    return removed


def depends_obsolete(latest_version, kind, req_version):
    req_version = Version(req_version)
    if kind == '>=':
        return latest_version >= req_version
    elif kind == '>>':
        return latest_version >> req_version
    elif kind == '=':
        return False
    return False


def conflict_obsolete(latest_version, kind, req_version):
    req_version = Version(req_version)
    if kind == '<<':
        return latest_version >= req_version
    elif kind in ('<=', '='):
        return latest_version >> req_version
    return False


async def _package_version(source, release):
    from .udd import connect_udd_mirror
    conn = await connect_udd_mirror()
    version = await conn.fetchval(
        "select version from sources where source = $1 and release = $2",
        source, release)
    if version is not None:
        return Version(version)
    return None


def package_version(source, upgrade_release):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_package_version(source, upgrade_release))


def drop_obsolete_depends(entry, upgrade_release):
    ors = []
    dropped = []
    for pkgrel in entry:
        if pkgrel.version is not None:
            compat_version = package_version(pkgrel.name, upgrade_release)
            if (compat_version is not None and
                    depends_obsolete(compat_version, *pkgrel.version)):
                pkgrel.version = None
                dropped.append(pkgrel)
        ors.append(pkgrel)
    return ors, dropped


def drop_obsolete_conflicts(entry, upgrade_release):
    ors = []
    dropped = []
    for pkgrel in entry:
        if pkgrel.version is not None:
            compat_version = package_version(pkgrel.name, upgrade_release)
            if (compat_version is not None and
                    conflict_obsolete(compat_version, *pkgrel.version)):
                dropped.append(pkgrel)
                continue
        ors.append(pkgrel)
    return ors, dropped


def update_depends(base, field, upgrade_release):
    try:
        old_contents = base[field]
    except KeyError:
        return []

    changed = []
    newrelations = []
    for ws1, oldrelation, ws2 in parse_relations(old_contents):
        relation, dropped = drop_obsolete_depends(oldrelation, upgrade_release)
        changed.extend([d.name for d in dropped])
        newrelations.append((ws1, relation, ws2))

    if changed:
        base[field] = format_relations(newrelations)
        return changed
    return []


def update_conflicts(base, field, upgrade_release):
    try:
        old_contents = base[field]
    except KeyError:
        return []

    changed = []
    newrelations = []
    for ws1, oldrelation, ws2 in parse_relations(old_contents):
        relation, dropped = drop_obsolete_conflicts(
            oldrelation, upgrade_release)
        changed.extend([d.name for d in dropped])
        newrelations.append((ws1, relation, ws2))

    if changed:
        base[field] = format_relations(newrelations)
        if not base[field]:
            del base[field]
        return changed
    return []


def drop_old_source_relations(source, upgrade_release):
    ret = []
    for field in [
            'Build-Depends', 'Build-Depends-Indep', 'Build-Depends-Arch',
            ]:
        packages = update_depends(source, field, upgrade_release)
        if packages:
            ret.append((field, packages))
    for field in [
            'Build-Conflicts', 'Build-Conflicts-Indep',
            'Build-Conflicts-Arch']:
        packages = update_conflicts(source, field, upgrade_release)
        if packages:
            ret.append((field, packages))
    return ret


def drop_old_binary_relations(binary, upgrade_release):
    ret = []
    for field in [
            'Depends', 'Breaks', 'Suggests', 'Recommends', 'Pre-Depends']:
        packages = update_depends(binary, field, upgrade_release)
        if packages:
            ret.append((field, packages))

    for field in ['Conflicts', 'Replaces', 'Breaks']:
        packages = update_conflicts(binary, field, upgrade_release)
        if packages:
            ret.append((field, packages))

    return ret


def drop_old_relations(editor, upgrade_release):
    dropped = []
    source_dropped = drop_old_source_relations(editor.source, upgrade_release)
    if source_dropped:
        dropped.append((None, source_dropped))

    for binary in editor.binaries:
        binary_dropped = drop_old_binary_relations(binary, upgrade_release)
        if binary_dropped:
            dropped.append((binary['Package'], binary_dropped))

    return dropped


def update_maintscripts(wt, path, package, upgrade_release):
    ret = []
    for entry in os.scandir(wt.abspath(os.path.join(path, 'debian'))):
        if not (entry.name == 'maintscript' or
                entry.name.endswith('.maintscript')):
            continue
        with MaintscriptEditor(entry.path) as editor:
            removed = drop_old_maintscript(editor, package, upgrade_release)
            if removed:
                ret.append((os.path.join(path, 'debian', entry.name), removed))
    return ret


class ScrubObsoleteResult(object):

    def __init__(self, specific_files, maintscript_removed,
                 control_removed):
        self.specific_files = specific_files
        self.maintscript_removed = maintscript_removed
        self.control_removed = control_removed

    def __bool__(self):
        return bool(self.control_removed) or bool(self.maintscript_removed)

    def itemized(self):
        summary = []
        for para, changes in self.control_removed:
            for field, packages in changes:
                if para:
                    summary.append(
                        '%s: Drop versioned constraint on %s in %s.' % (
                         para, ', '.join(packages), field))
                else:
                    summary.append(
                        '%s: Drop versioned constraint on %s.' % (
                         field, ', '.join(packages)))
        if self.maintscript_removed:
            summary.append('Remove %d maintscript entries.' %
                           len(self.maintscript_removed))
        return summary


def scrub_obsolete(wt, subpath, upgrade_release):
    specific_files = []
    control_path = os.path.join(subpath, 'debian/control')
    with ControlEditor(wt.abspath(control_path)) as editor:
        specific_files.append(control_path)
        package = editor.source['Source']
        control_removed = drop_old_relations(editor, upgrade_release)

    maintscript_removed = []
    for path, removed in update_maintscripts(
            wt, subpath, package, upgrade_release):
        if removed:
            maintscript_removed.append((path, removed))
            specific_files.append(path)

    return ScrubObsoleteResult(
        specific_files=specific_files,
        control_removed=control_removed,
        maintscript_removed=maintscript_removed)


def main():
    import argparse
    import os
    from breezy.workingtree import WorkingTree
    import breezy  # noqa: E402
    breezy.initialize()
    import breezy.git  # noqa: E402
    import breezy.bzr  # noqa: E402
    from breezy.trace import note  # note: E402
    from breezy.commit import NullCommitReporter

    from . import (
        check_clean_tree,
        PendingChanges,
        get_committer,
        version_string,
        )
    from .config import Config

    parser = argparse.ArgumentParser(prog='drop-backwards-compat')
    parser.add_argument(
        '--directory', metavar='DIRECTORY', help='directory to run in',
        type=str, default='.')
    parser.add_argument(
        '--upgrade-release', metavar='UPGRADE-RELEASE',
        help='Release to allow upgrading from.', default='oldstable')
    parser.add_argument(
        '--no-update-changelog', action="store_false", default=None,
        dest="update_changelog", help="do not update the changelog")
    parser.add_argument(
        '--update-changelog', action="store_true", dest="update_changelog",
        help="force updating of the changelog", default=None)
    parser.add_argument(
        '--version', action='version', version='%(prog)s ' + version_string)
    parser.add_argument(
        '--identity',
        help='Print user identity that would be used when committing',
        action='store_true', default=False)

    args = parser.parse_args()

    wt, subpath = WorkingTree.open_containing(args.directory)
    if args.identity:
        note(get_committer(wt))
        return 0

    try:
        check_clean_tree(wt, wt.basis_tree(), subpath)
    except PendingChanges:
        note("%s: Please commit pending changes first.", wt.basedir)
        return 1

    import distro_info
    debian_info = distro_info.DebianDistroInfo()
    upgrade_release = debian_info.codename(args.upgrade_release)

    result = scrub_obsolete(wt, subpath, upgrade_release)
    if not result:
        return 0

    specific_files = list(result.specific_files)
    summary = result.itemized()

    update_changelog = args.update_changelog
    try:
        cfg = Config.from_workingtree(wt, subpath)
    except FileNotFoundError:
        pass
    else:
        if update_changelog is None:
            update_changelog = cfg.update_changelog()
    changelog_path = os.path.join(subpath, 'debian/changelog')

    if update_changelog is None:
        from .detect_gbp_dch import guess_update_changelog
        from debian.changelog import Changelog
        with wt.get_file(changelog_path) as f:
            cl = Changelog(f, max_blocks=1)

        dch_guess = guess_update_changelog(wt, subpath, cl)
        if dch_guess:
            update_changelog = dch_guess[0]
            _note_changelog_policy(update_changelog, dch_guess[1])
        else:
            # Assume we should update changelog
            update_changelog = True

    if update_changelog:
        add_changelog_entry(
            wt, changelog_path,
            ['Remove constraints unnecessary since %s:' %
             upgrade_release] + ['+ ' + line for line in summary])
        specific_files.append(changelog_path)

    message = '\n'.join([
        'Remove constraints unnecessary since %s.' % upgrade_release, ''] +
        ['* ' + line for line in summary] +
        ['', 'Changes-By: deb-scrub-obsolete'])

    committer = get_committer(wt)

    wt.commit(
        specific_files=specific_files,
        message=message,
        allow_pointless=False,
        reporter=NullCommitReporter(),
        committer=committer)


if __name__ == '__main__':
    import sys
    sys.exit(main())
