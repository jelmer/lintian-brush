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

"""Tests for lintian_brush.changelog."""

from datetime import datetime

from breezy.tests import (
    TestCaseWithTransport,
)

from debian.changelog import (
    ChangelogCreateError,
)
from lintian_brush.changelog import (
    add_changelog_entry,
)


class ChangelogAddEntryTests(TestCaseWithTransport):
    def test_edit_existing_new_author(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Initial change.
  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Jane Example")
        self.overrideEnv("DEBEMAIL", "jane@example.com")
        add_changelog_entry(tree, "debian/changelog", ["Add a foo"])
        self.assertFileEqual(
            """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  [ Joe Example ]
  * Initial change.
  * Support updating templated debian/control files that use cdbs
    template.

  [ Jane Example ]
  * Add a foo

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_edit_existing_multi_new_author(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  [ Jane Example ]
  * Support updating templated debian/control files that use cdbs
    template.

  [ Joe Example ]
  * Another change

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Jane Example")
        self.overrideEnv("DEBEMAIL", "jane@example.com")
        add_changelog_entry(tree, "debian/changelog", ["Add a foo"])
        self.assertFileEqual(
            """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  [ Jane Example ]
  * Support updating templated debian/control files that use cdbs
    template.

  [ Joe Example ]
  * Another change

  [ Jane Example ]
  * Add a foo

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_edit_existing_existing_author(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Joe Example")
        self.overrideEnv("DEBEMAIL", "joe@example.com")
        add_changelog_entry(tree, "debian/changelog", ["Add a foo"])
        self.assertFileEqual(
            """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.
  * Add a foo

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_add_new(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) unstable; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Jane Example")
        self.overrideEnv("DEBEMAIL", "jane@example.com")
        self.overrideEnv("DEBCHANGE_VENDOR", "debian")
        add_changelog_entry(
            tree,
            "debian/changelog",
            ["Add a foo"],
            timestamp=datetime(2020, 5, 24, 15, 27, 26),
        )
        self.assertFileEqual(
            """\
lintian-brush (0.36) UNRELEASED; urgency=medium

  * Add a foo

 -- Jane Example <jane@example.com>  Sun, 24 May 2020 15:27:26 -0000

lintian-brush (0.35) unstable; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_edit_broken_first_line(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
THIS IS NOT A PARSEABLE LINE
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Jane Example")
        self.overrideEnv("DEBEMAIL", "jane@example.com")
        add_changelog_entry(tree, "debian/changelog", ["Add a foo", "+ Bar"])
        self.assertFileEqual(
            """\
THIS IS NOT A PARSEABLE LINE
lintian-brush (0.35) UNRELEASED; urgency=medium

  [ Joe Example ]
  * Support updating templated debian/control files that use cdbs
    template.

  [ Jane Example ]
  * Add a foo
    + Bar

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_add_long_line(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Joe Example")
        self.overrideEnv("DEBEMAIL", "joe@example.com")
        add_changelog_entry(
            tree,
            "debian/changelog",
            [
                "This is adding a very long sentence that is longer than "
                "would fit on a single line in a 80-character-wide line."
            ],
        )
        self.assertFileEqual(
            """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.
  * This is adding a very long sentence that is longer than would fit on a
    single line in a 80-character-wide line.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_add_long_subline(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Joe Example")
        self.overrideEnv("DEBEMAIL", "joe@example.com")
        add_changelog_entry(
            tree,
            "debian/changelog",
            [
                "This is the main item.",
                "+ This is adding a very long sentence that is longer than "
                "would fit on a single line in a 80-character-wide line.",
            ],
        )
        self.assertFileEqual(
            """\
lintian-brush (0.35) UNRELEASED; urgency=medium

  * Support updating templated debian/control files that use cdbs
    template.
  * This is the main item.
    + This is adding a very long sentence that is longer than would fit on a
      single line in a 80-character-wide line.

 -- Joe Example <joe@example.com>  Fri, 04 Oct 2019 02:36:13 +0000
""",
            "debian/changelog",
        )

    def test_trailer_only(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) unstable; urgency=medium

  * This line already existed.

 --
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Joe Example")
        self.overrideEnv("DEBEMAIL", "joe@example.com")
        try:
            add_changelog_entry(
                tree, "debian/changelog", ["And this one is new."]
            )
        except ChangelogCreateError:
            self.skipTest(
                "python-debian does not allow serializing changelog "
                "with empty trailer"
            )
        self.assertFileEqual(
            """\
lintian-brush (0.35) unstable; urgency=medium

  * This line already existed.
  * And this one is new.

 --
""",
            "debian/changelog",
        )

    def test_trailer_only_existing_author(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/changelog",
                    """\
lintian-brush (0.35) unstable; urgency=medium

  * This line already existed.

  [ Jane Example ]
  * And this one has an existing author.

 --
""",
                ),
            ]
        )
        tree.add(["debian", "debian/changelog"])
        self.overrideEnv("DEBFULLNAME", "Joe Example")
        self.overrideEnv("DEBEMAIL", "joe@example.com")
        try:
            add_changelog_entry(
                tree, "debian/changelog", ["And this one is new."]
            )
        except ChangelogCreateError:
            self.skipTest(
                "python-debian does not allow serializing changelog "
                "with empty trailer"
            )
        self.assertFileEqual(
            """\
lintian-brush (0.35) unstable; urgency=medium

  * This line already existed.

  [ Jane Example ]
  * And this one has an existing author.

  [ Joe Example ]
  * And this one is new.

 --
""",
            "debian/changelog",
        )
