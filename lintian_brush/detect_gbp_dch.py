#!/usr/bin/python
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

"""Detect gbp dch policy."""


import os
from typing import Optional, Tuple, List

from debian.changelog import Changelog
from debmutate.changelog import (
    all_sha_prefixed,
    is_unreleased_inaugural,
    )

from breezy import osutils
from breezy.branch import Branch
from breezy.errors import NoSuchFile, RevisionNotPresent
from breezy.tree import Tree
from breezy.workingtree import WorkingTree


# Number of revisions to search back
DEFAULT_BACKLOG = 50


# TODO(jelmer): Check that what's added in the changelog is actually based on
# what was in the commit messages?


def gbp_conf_has_dch_section(tree: WorkingTree, debian_path: str = "") -> Optional[bool]:
    try:
        gbp_conf_path = osutils.pathjoin(debian_path, "gbp.conf")
        gbp_conf_text = tree.get_file_text(gbp_conf_path)
    except NoSuchFile:
        return False
    try:
        import configparser
    except ImportError:
        return None
    else:
        parser = configparser.ConfigParser(defaults={}, strict=False)
        parser.read_string(
            gbp_conf_text.decode("utf-8", errors="replace"), gbp_conf_path
        )
        return parser.has_section("dch")


def guess_update_changelog(
    tree: WorkingTree, debian_path: str, cl: Optional[Changelog] = None
) -> Optional[Tuple[bool, str]]:
    """Guess whether the changelog should be updated.

    Args:
      tree: Tree to edit
      debian_path: Path to packaging in tree
    Returns:
      best guess at whether we should update changelog (bool)
    """
    if debian_path != "debian":
        return (
            True,
            "assuming changelog needs to be updated since "
            "gbp dch only suppors a debian directory in the root of the "
            "repository")
    changelog_path = osutils.pathjoin(debian_path, "changelog")
    if cl is None:
        try:
            with tree.get_file(changelog_path) as f:
                cl = Changelog(f)
        except NoSuchFile:
            cl = None
    if cl and is_unreleased_inaugural(cl):
        return (
            False,
            "assuming changelog does not need to be updated "
            "since it is the inaugural unreleased entry")
    ret = _guess_update_changelog_from_tree(tree, debian_path, cl)
    if ret is not None:
        return ret
    ret = _guess_update_changelog_from_branch(tree.branch, debian_path)
    if ret is not None:
        return ret
    return None


def _guess_update_changelog_from_tree(
    tree: Tree, debian_path: str, cl: Optional[Changelog]
) -> Optional[Tuple[bool, str]]:
    if gbp_conf_has_dch_section(tree, debian_path):
        return (
            False,
            "Assuming changelog does not need to be updated, "
            "since there is a [dch] section in gbp.conf.",
        )

    # TODO(jelmes): Do something more clever here, perhaps looking at history
    # of the changelog file?
    if cl:
        if all_sha_prefixed(cl[0]):
            return (
                False,
                "Assuming changelog does not need to be updated, "
                "since all entries in last changelog entry are prefixed "
                "by git shas.",
            )

    return None


def _greedy_revisions(graph, revid: bytes, length: int) -> Tuple[List[bytes], bool]:
    ret: List[bytes] = []
    it = graph.iter_lefthand_ancestry(revid)
    while len(ret) < length:
        try:
            ret.append(next(it))
        except StopIteration:
            break
        except RevisionNotPresent:
            if ret:
                ret.pop(-1)
            # Shallow history
            return ret, True
    return ret, False


def _changelog_stats(branch: Branch, history: int, debian_path: str):
    mixed = 0
    changelog_only = 0
    other_only = 0
    dch_references = 0
    with branch.lock_read():
        graph = branch.repository.get_graph()
        revids, truncated = _greedy_revisions(graph, branch.last_revision(), history)
        revs = []
        for revid, rev in branch.repository.iter_revisions(revids):
            if rev is None:
                # Ghost
                continue
            if "Git-Dch: " in rev.message:
                dch_references += 1
            revs.append(rev)
        try:
            get_deltas = branch.repository.get_revision_deltas
        except AttributeError:  # breezy <= 3.1.1
            get_deltas = branch.repository.get_deltas_for_revisions
        for delta in get_deltas(revs):
            filenames = set(
                [a.path[1] for a in delta.added]
                + [r.path[0] for r in delta.removed]
                + [r.path[0] for r in delta.renamed]
                + [r.path[1] for r in delta.renamed]
                + [m.path[0] for m in delta.modified]
            )
            if not set(
                [
                    f
                    for f in filenames
                    if f.startswith(debian_path + '/')
                ]
            ):
                continue
            if osutils.pathjoin(debian_path, "changelog") in filenames:
                if len(filenames) > 1:
                    mixed += 1
                else:
                    changelog_only += 1
            else:
                other_only += 1
    return (changelog_only, other_only, mixed, dch_references)


def _guess_update_changelog_from_branch(
    branch: Branch, debian_path: str = "", history: int = DEFAULT_BACKLOG
) -> Optional[Tuple[bool, str]]:
    """Guess whether the changelog should be updated manually.

    Args:
      branch: A branch object
      history: Number of revisions back to analyze
    Returns:
      boolean indicating whether changelog should be updated
    """
    # Two indications this branch may be doing changelog entries at
    # release time:
    # - "Git-Dch: " is used in the commit messages
    # - The vast majority of lines in changelog get added in
    #   commits that only touch the changelog
    (changelog_only, other_only, mixed, dch_references) = _changelog_stats(
        branch, history, debian_path
    )
    if dch_references:
        return (
            False,
            "Assuming changelog does not need to be updated, since "
            "there are Gbp-Dch stanzas in commit messages",
        )
    if changelog_only == 0:
        return (
            True,
            "Assuming changelog needs to be updated, since "
            "it is always changed together with other files in the tree.",
        )
    if mixed == 0 and changelog_only > 0 and other_only > 0:
        # changelog is *always* updated in a separate commit.
        return (
            False,
            "Assuming changelog does not need to be updated, since "
            "changelog entries are always updated in separate commits.",
        )
    # Is this a reasonable threshold?
    if changelog_only > mixed and other_only > mixed:
        return (
            False,
            "Assuming changelog does not need to be updated, since "
            "changelog entries are usually updated in separate commits.",
        )
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    wt, subpath = WorkingTree.open_containing(".")
    from . import control_files_in_root
    if control_files_in_root(wt, subpath):
        debian_path = subpath
    else:
        debian_path = os.path.join(subpath, "debian")
    print(guess_update_changelog(wt, debian_path))
