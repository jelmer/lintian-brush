#!/usr/bin/python

from breezy.trace import note

import os
import subprocess


class NoChanges(Exception):
    """Script didn't make any changes."""


class ScriptFailed(Exception):
    """Script failed to run."""


class Fixer(object):

    def __init__(self, tag, script_path):
        self.tag = tag
        self.script_path = script_path


def available_lintian_fixers():
    fixer_scripts = {}
    fixers_dir = os.path.join(os.path.dirname(__file__), 'fixers', 'lintian')
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
    p = subprocess.Popen(fixer.script_path, cwd=local_tree.basedir, stdout=subprocess.PIPE)
    (description, err) = p.communicate("")
    if p.returncode != 0:
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

if __name__ == '__main__':
    import argparse
    import sys
    from breezy.workingtree import WorkingTree
    import locale
    locale.setlocale(locale.LC_ALL, '')
    # Use better default than ascii with posix filesystems that deal in bytes
    # natively even when the C locale or no locale at all is given. Note that
    # we need an immortal string for the hack, hence the lack of a hyphen.
    sys._brz_default_fs_enc = "utf8"

    import breezy
    breezy.initialize()
    import breezy.git
    import breezy.bzr
    import breezy.plugins.launchpad
    import breezy.plugins.debian # for apt: urls

    parser = argparse.ArgumentParser()
    parser.add_argument('--no-update-changelog', action="store_true", help="Whether to update the changelog.")
    parser.add_argument('fixers', metavar='TAGS', nargs='*', help='Lintian tag for which to apply fixer.')
    args = parser.parse_args()

    wt = WorkingTree.open('.')
    fixers = available_lintian_fixers()
    if args.fixers:
        fixers = [f for f in fixers if f.tag in args.fixers]
    with wt.lock_write():
        run_lintian_fixers(wt, fixers, update_changelog=(not args.no_update_changelog))
