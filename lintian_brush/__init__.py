#!/usr/bin/python
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

"""Automatically fix lintian issues."""

__version__ = (0, 1)
version_string = '.'.join(map(str, __version__))

from breezy.rename_map import RenameMap
from breezy.trace import note

import os
import subprocess
import sys


class NoChanges(Exception):
    """Script didn't make any changes."""


class ScriptFailed(Exception):
    """Script failed to run."""


class Fixer(object):

    def __init__(self, tag, script_path):
        self.tag = tag
        self.script_path = script_path


def find_fixers_dir():
    local_dir = os.path.join(os.path.dirname(__file__), '..', 'fixers', 'lintian')
    if os.path.isdir(local_dir):
        return local_dir
    import pkg_resources

    return pkg_resources.resource_filename(__name__, 'lintian-brush/fixers/lintian')


def available_lintian_fixers():
    fixer_scripts = {}
    fixers_dir = find_fixers_dir()
    for n in os.listdir(fixers_dir):
        if n.endswith("~") or n.startswith("."):
            continue
        tag = os.path.splitext(n)[0]
        path = os.path.join(fixers_dir, n)
        yield Fixer(tag, path)


def run_lintian_fixer(local_tree, fixer, update_changelog=True):
    """Run a lintian fixer on a tree.

    Args:
      local_tree: WorkingTree object
      fixer: Fixer object to apply
      update_changelog: Whether to add a new entry to the changelog
    Returns:
      summary of the changes
    """
    # Just check there are no changes to begin with
    if list(local_tree.iter_changes(local_tree.basis_tree())):
        raise AssertionError("Local tree %s has changes" % local_tree.basedir)
    note('Running fixer %s on %s', fixer.tag, local_tree.branch.user_url)
    p = subprocess.Popen(fixer.script_path, cwd=local_tree.basedir,
                         stdout=subprocess.PIPE, stderr=sys.stderr)
    unknowns = list(local_tree.unknowns())
    if unknowns:
        # Urgh.
        local_tree.add([f for f in unknowns if not os.path.basename(f).startswith('sed')])
    if local_tree.supports_setting_file_ids():
        RenameMap.guess_renames(local_tree.basis_tree(), local_tree, dry_run=False)
    (description, err) = p.communicate("")
    if p.returncode != 0:
        # TODO(jelmer): Clean tree; revert changes, remove unknowns
        raise ScriptFailed("Script %s failed with error code %d" % (
                fixer.script_path, p.returncode))

    summary = description.splitlines()[0]

    if not list(local_tree.iter_changes(local_tree.basis_tree())):
        raise NoChanges("Script didn't make any changes")

    if update_changelog:
        subprocess.check_call(
            ["dch", "--no-auto-nmu", summary],
            cwd=local_tree.basedir)

    description += "\n"
    description += "Fixes lintian: %s\n" % fixer.tag
    description += "See https://lintian.debian.org/tags/%s.html for more details.\n" % fixer.tag

    local_tree.commit(description, allow_pointless=False)
    # TODO(jelmer): Run sbuild & verify lintian warning is gone?
    return summary


def run_lintian_fixers(local_tree, fixers, update_changelog=True):
    ret = []
    for fixer in fixers:
        try:
            description = run_lintian_fixer(
                    local_tree, fixer, update_changelog)
        except ScriptFailed:
            note('Script for %s failed to run', fixer.tag)
        except NoChanges:
            pass
        else:
            ret.append((fixer.tag, description))
    return ret

