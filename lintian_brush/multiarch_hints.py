#!/usr/bin/python3
# Copyright (C) 2019-2020 Jelmer Vernooij
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

"""Utility functions for applying multi-arch hints."""

import contextlib
import os
import re
import sys
import time

from urllib.error import HTTPError
from urllib.request import urlopen, Request

from lintian_brush import (
    get_committer,
    version_string,
    )
from debmutate.control import (
    ControlEditor,
    format_relations,
    parse_relations,
    )


USER_AGENT = 'apply-multiarch-hints/' + version_string
MULTIARCH_HINTS_URL = 'https://dedup.debian.net/static/multiarch-hints.yaml.xz'
DEFAULT_URLLIB_TIMEOUT = 10


def parse_multiarch_hints(f):
    """Parse a multi-arch hints file.

    Args:
      f: File-like object to read from
    Returns:
      dictionary mapping binary package names to lists of hints
    """
    from ruamel.yaml import YAML
    yaml = YAML(typ='safe')
    data = yaml.load(f)
    if data.get('format') != 'multiarch-hints-1.0':
        raise ValueError('invalid file format: %r' % data.get('format'))
    return data['hints']


def multiarch_hints_by_binary(hints):
    ret = {}
    for entry in hints:
        ret.setdefault(entry['binary'], []).append(entry)
    return ret


def multiarch_hints_by_source(hints):
    ret = {}
    for entry in hints:
        if 'source' not in entry:
            continue
        ret.setdefault(entry['source'], []).append(entry)
    return ret


@contextlib.contextmanager
def cache_download_multiarch_hints(url=MULTIARCH_HINTS_URL):
    """Load multi-arch hints from a URL, but use cached version if available.
    """
    from breezy.trace import note, warning
    cache_home = os.environ.get('XDG_CACHE_HOME')
    if not cache_home:
        cache_home = os.path.expanduser('~/.cache')
    cache_dir = os.path.join(cache_home, 'lintian-brush')
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except PermissionError:
        local_hints_path = None
        warning('Unable to create %s; not caching.', cache_dir)
    else:
        local_hints_path = os.path.join(cache_dir, 'multiarch-hints.yml')
    try:
        last_modified = os.path.getmtime(local_hints_path)
    except FileNotFoundError:
        last_modified = None
    try:
        with download_multiarch_hints(
                url=url, since=last_modified) as f:
            if local_hints_path is None:
                yield f
                return
            note('Downloading new version of multi-arch hints.')
            with open(local_hints_path, 'wb') as c:
                c.writelines(f)
    except HTTPError as e:
        if e.status != 304:
            raise
    yield open(local_hints_path, 'rb')


@contextlib.contextmanager
def download_multiarch_hints(url=MULTIARCH_HINTS_URL, since: int = None):
    """Load multi-arch hints from a URL.

    Args:
      url: URL to read from
      since: Last modified timestamp
    Returns:
      multi-arch hints file
    """
    headers = {'User-Agent': USER_AGENT}
    if since is not None:
        headers['If-Modified-Since'] = time.strftime(
            '%a, %d %b %Y %H:%M:%S GMT', time.gmtime(since))

    with urlopen(
            Request(url, headers=headers),
            timeout=DEFAULT_URLLIB_TIMEOUT) as f:
        if url.endswith('.xz'):
            import lzma
            # It would be nicer if there was a content-type, but there isn't
            # :-(
            f = lzma.LZMAFile(f)
        yield f


def apply_hint_ma_foreign(binary, hint):
    if binary.get('Multi-Arch') != 'foreign':
        binary['Multi-Arch'] = 'foreign'
        return 'Add Multi-Arch: foreign.'


def apply_hint_ma_foreign_lib(binary, hint):
    if binary.get('Multi-Arch') == 'foreign':
        del binary['Multi-Arch']
        return 'Drop Multi-Arch: foreign.'


def apply_hint_file_conflict(binary, hint):
    if binary.get('Multi-Arch') == 'same':
        del binary['Multi-Arch']
        return 'Drop Multi-Arch: same.'


def apply_hint_dep_any(binary, hint):
    m = re.match(
        '(.*) could have its dependency on (.*) annotated with :any',
        hint['description'])
    if not m or m.group(1) != binary['Package']:
        raise ValueError(
            'unable to parse hint description: %r' % hint['description'])
    dep = m.group(2)
    if 'Depends' not in binary:
        return
    changed = False
    relations = parse_relations(binary['Depends'])
    for entry in relations:
        (head_whitespace, relation, tail_whitespace) = entry
        if not isinstance(relation, str):  # formatting
            for r in relation:
                if r.name == dep and r.archqual != 'any':
                    r.archqual = 'any'
                    changed = True
    if not changed:
        return
    binary['Depends'] = format_relations(relations)
    return ('Add :all qualifier for %s dependency.' % dep)


def apply_hint_ma_same(binary, hint):
    if binary.get('Multi-Arch') == 'same':
        return
    binary['Multi-Arch'] = 'same'
    return 'Add Multi-Arch: same.'


def apply_hint_arch_all(binary, hint):
    if binary['Architecture'] == 'all':
        return
    binary['Architecture'] = 'all'
    return 'Make package Architecture: all.'


def apply_multiarch_hints(path, hints, kinds):
    changes = []
    with ControlEditor(path) as editor:
        for binary in editor.binaries:
            for hint in hints.get(binary['Package'], []):
                kind = hint['link'].rsplit('#', 1)[1]
                if kind in kinds:
                    continue
                applier = APPLIERS[kind]
                description = applier(binary, hint)
                if description:
                    changes.append(
                        (binary, hint, description, kind))
    return changes


APPLIERS = {
    'ma-foreign': apply_hint_ma_foreign,
    'file-conflict': apply_hint_file_conflict,
    'ma-foreign-library': apply_hint_ma_foreign_lib,
    'dep-any': apply_hint_dep_any,
    'ma-same': apply_hint_ma_same,
    'arch-all': apply_hint_arch_all,
}


def main(argv=None):
    from debian.changelog import Changelog
    import argparse
    from breezy.workingtree import WorkingTree
    from breezy.errors import NoSuchFile

    import breezy  # noqa: E402
    breezy.initialize()
    from breezy.commit import NullCommitReporter
    import breezy.git  # noqa: E402
    import breezy.bzr  # noqa: E402
    from breezy.trace import note  # noqa: E402
    from breezy.workspace import Workspace, WorkspaceDirty

    from .config import Config

    parser = argparse.ArgumentParser(prog='multi-arch-fixer')
    parser.add_argument(
        '--directory', metavar='DIRECTORY', help='directory to run in',
        type=str, default='.')
    parser.add_argument(
        '--disable-inotify', action='store_true', default=False,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--identity',
        help='Print user identity that would be used when committing',
        action='store_true', default=False)
    parser.add_argument(
        '--no-update-changelog', action="store_false", default=None,
        dest="update_changelog", help="do not update the changelog")
    parser.add_argument(
        '--update-changelog', action="store_true", dest="update_changelog",
        help="force updating of the changelog", default=None)
    parser.add_argument(
        '--kinds', choices=list(APPLIERS.keys()), nargs="+",
        default=['ma-foreign', 'file-conflict', 'ma-foreign-library',
                 'dep-any', 'ma-same'],
        help='Which kinds of multi-arch hints to apply.')
    parser.add_argument(
        '--version', action='version', version='%(prog)s ' + version_string)
    parser.add_argument(
        '--allow-reformatting', default=None, action='store_true',
        help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    use_inotify = (False if args.disable_inotify else None),
    ws = Workspace.from_path(args.directory, use_inotify=use_inotify)
    if args.identity:
        note(get_committer(ws.tree))
        return 0

    update_changelog = args.update_changelog
    try:
        cfg = Config.from_workspace(ws)
    except FileNotFoundError:
        pass
    else:
        if update_changelog is None:
            update_changelog = cfg.update_changelog()

    with cache_download_multiarch_hints() as f:
        hints = multiarch_hints_by_binary(parse_multiarch_hints(f))

    try:
        with ws:
            changelog_path = ws.tree_path('debian/changelog')
            try:
                with ws.tree.get_file(changelog_path) as f:
                    cl = Changelog(f, max_blocks=1)
            except NoSuchFile:
                note("%s: Not a debian package.", ws.abspath())
                return 1

            changes = apply_multiarch_hints(
                ws.abspath('debian/control'), hints, args.kinds)

            if not changes:
                note('Nothing to do.')
                return 0

            overall_description = "Apply multi-arch hints.\n" + "\n".join(
                ["+ %s: %s" % (binary['Package'], description)
                 for (binary, hint, description, kind) in changes])

            if update_changelog is None:
                from .detect_gbp_dch import guess_update_changelog
                dch_guess = guess_update_changelog(ws.tree, ws.subpath, cl)
                if dch_guess:
                    update_changelog, explanation = dch_guess
                    if update_changelog:
                        extra = 'Specify --no-update-changelog to override.'
                    else:
                        extra = 'Specify --update-changelog to override.'
                    note('%s %s', explanation, extra)
                else:
                    # Assume we should update changelog
                    update_changelog = True

            if update_changelog:
                from .changelog import add_changelog_entry
                add_changelog_entry(
                    ws.tree, changelog_path, overall_description)

            description = overall_description + "\n"
            description += "\n"
            description += "Changes-By: apply-multiarch-hints\n"

            committer = get_committer(ws.tree)

            ws.commit(
                message=description, allow_pointless=False,
                reporter=NullCommitReporter(),
                committer=committer)
            for binary, hint, description, kind in changes:
                note('%s: %s' % (binary['Package'], description))
    except WorkspaceDirty:
        note("%s: Please commit pending changes first.", ws.abspath())
        return 1


if __name__ == '__main__':
    sys.exit(main())
