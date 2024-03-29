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

"""Tests for lintian_brush.detect_gbp_dch."""

from breezy.tests import (
    TestCaseWithTransport,
)

from ..detect_gbp_dch import (
    ChangelogBehaviour,
    guess_update_changelog,
)


def make_changelog(entries):
    return (
        """\
lintian-brush (0.1) UNRELEASED; urgency=medium

"""
        + "".join(["  * %s\n" % entry for entry in entries])
        + """

 -- Jelmer Vernooij <jelmer@debian.org>  Sat, 13 Oct 2018 11:21:39 +0100
"""
    ).encode("utf-8")


class GuessUpdateChangelogTests(TestCaseWithTransport):
    def test_no_gbp_conf(self):
        tree = self.make_branch_and_tree(".")
        self.assertEqual(
            ChangelogBehaviour(
                True,
                "Assuming changelog needs to be updated, "
                "since it is always changed together "
                "with other files in the tree.",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_custom_path(self):
        tree = self.make_branch_and_tree(".")
        self.assertEqual(
            ChangelogBehaviour(
                True,
                "Assuming changelog needs to be updated, "
                "since it is always changed together "
                "with other files in the tree.",
            ),
            guess_update_changelog(tree, "debian"),
        )
        self.assertEqual(
            ChangelogBehaviour(
                True,
                "assuming changelog needs to be updated since "
                "gbp dch only supports a debian "
                "directory in the root of the repository",
            ),
            guess_update_changelog(tree, ""),
        )
        self.assertEqual(
            ChangelogBehaviour(
                True,
                "assuming changelog needs to be updated since "
                "gbp dch only supports a debian "
                "directory in the root of the repository",
            ),
            guess_update_changelog(tree, "lala/debian"),
        )

    def test_gbp_conf_dch(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/gbp.conf",
                    """\
[dch]
pristine-tar = False
""",
                ),
            ]
        )
        tree.add(["debian", "debian/gbp.conf"])
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "Assuming changelog does not need to be updated, since "
                "there is a [dch] section in gbp.conf.",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_changelog_sha_prefixed(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
blah (0.20.1) unstable; urgency=medium

  [ Somebody ]
  * [ebb7c31] do a thing
  * [629746a] do another thing that actually requires us to wrap lines
    and then

  [ Somebody Else ]
  * [b02b435] do another thing

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "Assuming changelog does not need to be updated, "
                "since all entries in last changelog entry are prefixed "
                "by git shas.",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_empty(self):
        tree = self.make_branch_and_tree(".")
        self.assertEqual(
            ChangelogBehaviour(
                True,
                "Assuming changelog needs to be updated, "
                "since it is always changed together "
                "with other files in the tree.",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_update_with_change(self):
        builder = self.make_branch_builder(".")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("upstream", None, "file", b"upstream")),
                ("add", ("debian/", None, "directory", "")),
                (
                    "add",
                    (
                        "debian/changelog",
                        None,
                        "file",
                        make_changelog(["initial release"]),
                    ),
                ),
                ("add", ("debian/control", None, "file", b"initial")),
            ],
            message="Initial\n",
        )
        changelog_entries = ["initial release"]
        for i in range(20):
            builder.build_snapshot(
                None,
                [("modify", ("upstream", b"upstream %d" % i))],
                message="Upstream",
            )
            changelog_entries.append("next entry %d" % i)
            builder.build_snapshot(
                None,
                [
                    (
                        "modify",
                        (
                            "debian/changelog",
                            make_changelog(changelog_entries),
                        ),
                    ),
                    ("modify", ("debian/control", b"next %d" % i)),
                ],
                message="Next",
            )
        builder.finish_series()
        branch = builder.get_branch()
        tree = branch.controldir.create_workingtree()
        self.assertEqual(
            ChangelogBehaviour(
                True,
                "Assuming changelog needs to be updated, "
                "since it is always changed together "
                "with other files in the tree.",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_changelog_updated_separately(self):
        builder = self.make_branch_builder(".")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", None, "directory", "")),
                ("add", ("debian/", None, "directory", "")),
                (
                    "add",
                    (
                        "debian/changelog",
                        None,
                        "file",
                        make_changelog(["initial release"]),
                    ),
                ),
                ("add", ("debian/control", None, "file", b"initial")),
            ],
            message="Initial\n",
        )
        changelog_entries = ["initial release"]
        for i in range(20):
            changelog_entries.append("next entry %d" % i)
            builder.build_snapshot(
                None,
                [("modify", ("debian/control", b"next %d" % i))],
                message="Next\n",
            )
        builder.build_snapshot(
            None,
            [
                (
                    "modify",
                    ("debian/changelog", make_changelog(changelog_entries)),
                )
            ],
        )
        changelog_entries.append("final entry")
        builder.build_snapshot(
            None, [("modify", ("debian/control", b"more"))], message="Next\n"
        )
        builder.build_snapshot(
            None,
            [
                (
                    "modify",
                    ("debian/changelog", make_changelog(changelog_entries)),
                )
            ],
        )
        builder.finish_series()
        branch = builder.get_branch()
        tree = branch.controldir.create_workingtree()
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "Assuming changelog does not need to be updated, "
                "since changelog entries are usually updated in "
                "separate commits.",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_has_dch_in_messages(self):
        builder = self.make_branch_builder(".")
        builder.build_snapshot(
            None,
            [("add", ("", None, "directory", ""))],
            message="Git-Dch: ignore\n",
        )
        branch = builder.get_branch()
        tree = branch.controldir.create_workingtree()
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "Assuming changelog does not need to be updated, "
                "since there are Gbp-Dch stanzas in commit messages",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_inaugural_unreleased(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
blah (0.20.1) UNRELEASED; urgency=medium

  * Initial release. Closes: #123123

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "assuming changelog does not need to be "
                "updated since it is the inaugural unreleased entry",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_last_entry_warns_generated(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
blah (0.20.1) UNRELEASED; urgency=medium

  * WIP (generated at release time: please do not add entries below).

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100

blah (0.20.1) unstable; urgency=medium

  * Initial release. Closes: #123123

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "last changelog entry warns changelog is generated "
                "at release time",
            ),
            guess_update_changelog(tree, "debian"),
        )

    def test_never_unreleased(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                ("debian/control", "foo"),
                (
                    "debian/changelog",
                    """\
blah (0.20.1) unstable; urgency=medium

  * Initial release. Closes: #123123

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100
""",
                ),
            ]
        )
        tree.add(["debian", "debian/control", "debian/changelog"])
        tree.commit("rev1")
        self.build_tree_contents([("debian/control", "bar")])
        tree.commit("rev2")
        self.build_tree_contents([("debian/control", "bla")])
        tree.commit("rev2")
        self.build_tree_contents(
            [
                (
                    "debian/changelog",
                    """\
blah (0.21.1) unstable; urgency=medium

  * Next release.

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100

blah (0.20.1) unstable; urgency=medium

  * Initial release. Closes: #123123

 -- Joe User <joe@example.com>  Tue, 19 Nov 2019 15:29:47 +0100
""",
                ),
            ]
        )
        tree.commit("rev2")
        self.assertEqual(
            ChangelogBehaviour(
                False,
                "Assuming changelog does not need to be updated, "
                "since it never uses UNRELEASED entries",
            ),
            guess_update_changelog(tree, "debian"),
        )
