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

"""Tests for lintian_brush.lintian_overrides."""

import os
import re
import subprocess

from breezy.tests import (
    TestCase,
    TestCaseWithTransport,
)

from lintian_brush.lintian_overrides import (
    INFO_FIXERS,
    LintianOverride,
    fix_override_info,
    get_overrides,
    load_renamed_tags,
    override_exists,
    overrides_paths,
    update_overrides_file,
)


class OverridesPathTests(TestCaseWithTransport):
    def test_no_overrides_paths(self):
        self.assertEqual([], list(overrides_paths()))

    def test_overrides_paths(self):
        self.build_tree(
            ["debian/", "debian/source/", "debian/source/lintian-overrides"]
        )
        self.assertEqual(
            ["debian/source/lintian-overrides"], list(overrides_paths())
        )


class UpdateOverridesFileTests(TestCaseWithTransport):
    def test_no_changes(self):
        CONTENT = """\
# An architecture wildcard would look like:
foo [any-i386] binary: another-tag optional-extra
"""
        self.build_tree_contents([("overrides", CONTENT)])

        def cb(lineno, override):
            return override

        self.assertFalse(update_overrides_file(cb=cb, path="overrides"))
        self.assertFileEqual(CONTENT, "overrides")

    def test_delete_last(self):
        CONTENT = """\
# An architecture wildcard would look like:
foo [any-i386] binary: another-tag optional-extra
"""
        self.build_tree_contents([("overrides", CONTENT)])

        def cb(lineno, override):
            return None

        self.assertTrue(update_overrides_file(cb=cb, path="overrides"))
        self.assertFalse(os.path.exists("overrides"))

    def test_delete(self):
        CONTENT = """\
# An architecture wildcard would look like:
foo [any-i386] binary: another-tag optional-extra
bar binary: onetag
"""
        self.build_tree_contents([("overrides", CONTENT)])

        def cb(lineno, override):
            return override if override.tag != "another-tag" else None

        self.assertTrue(update_overrides_file(cb=cb, path="overrides"))
        self.assertFileEqual("bar binary: onetag\n", "overrides")

    def test_change_set_archlist(self):
        self.build_tree_contents(
            [
                (
                    "overrides",
                    """\
# An architecture wildcard would look like:
foo binary: another-tag optional-extra
""",
                )
            ]
        )

        def cb(lineno, override):
            return LintianOverride(
                tag=override.tag,
                package=override.package,
                type=override.type,
                info=override.info,
                archlist=["any-i386"],
            )

        self.assertTrue(update_overrides_file(cb=cb, path="overrides"))
        self.assertFileEqual(
            """\
# An architecture wildcard would look like:
foo [any-i386] binary: another-tag optional-extra
""",
            "overrides",
        )


class OverrideExistsTests(TestCaseWithTransport):
    def test_override_exists(self):
        self.build_tree_contents(
            [
                ("debian/",),
                ("debian/source/",),
                (
                    "debian/source/lintian-overrides",
                    """\
blah source: patch-file-exists-but info
""",
                ),
            ]
        )
        self.assertEqual(
            [
                LintianOverride(
                    package="blah",
                    archlist=None,
                    type="source",
                    tag="patch-file-exists-but",
                    info="info",
                )
            ],
            list(get_overrides()),
        )
        self.assertTrue(override_exists("patch-file-exists-but", info="info"))
        self.assertFalse(override_exists("patch-file-exists-but", info="no"))
        self.assertTrue(
            override_exists(
                tag="patch-file-exists-but", info="info", package="blah"
            )
        )


class InfoFixerTests(TestCase):
    def test_tags_known(self):
        tags = {
            x.decode()
            for x in subprocess.check_output(
                ["lintian-explain-tags", "--list-tags"]
            ).splitlines(False)
        }
        tags.update(load_renamed_tags())
        for tag in INFO_FIXERS:
            self.assertIn(tag, tags)

    def test_valid_regexes(self):
        for v in INFO_FIXERS.values():
            if isinstance(v, tuple):
                vs = [v]
            elif isinstance(v, list):
                vs = v
            for v in vs:
                if isinstance(v, tuple):
                    try:
                        re.compile(v[0])
                    except re.error as e:
                        self.fail(f"Invalid regex {v[0]}: {e}")


INFO_FIXER_TESTS = [
    ("maintainer-manual-page", "*", "[*]"),
    ("source-is-missing", "lib/hash/md4.js", "[lib/hash/md4.js]"),
    ("source-is-missing", "lib/hash/md4.js *", "[lib/hash/md4.js]"),
    (
        "source-is-missing",
        "test/integration/client/big-simple-query-tests.js line "
        "length is 1118 characters (>512)",
        "[test/integration/client/big-simple-query-tests.js]",
    ),
    (
        "source-contains-prebuilt-javascript-object",
        "lib/hash/md5.js",
        "[lib/hash/md5.js]",
    ),
    (
        "very-long-line-length-in-source-file",
        "debian/gbp.conf *",
        "* [debian/gbp.conf:*]",
    ),
    (
        "very-long-line-length-in-source-file",
        "benchmark/samples/lorem1.txt line 3 is 881 characters long (>512)",
        "881 > 512 [benchmark/samples/lorem1.txt:3]",
    ),
    (
        "very-long-line-length-in-source-file",
        "docs/*.css line *",
        "* [docs/*.css:*]",
    ),
    (
        "missing-license-text-in-dep5-copyright",
        "debian/copyright GPL-3\\+ *",
        "GPL-3\\+ [debian/copyright:*]",
    ),
    (
        "inconsistent-appstream-metadata-license",
        "menu/peg-solitaire.appdata.xml (gpl-3.0+ != gpl-3+)",
        "menu/peg-solitaire.appdata.xml (gpl-3.0+ != gpl-3+) [debian/copyright]",
    ),
    (
        "source-ships-excluded-file",
        "compiler/gradle/wrapper/gradle-wrapper.jar",
        "compiler/gradle/wrapper/gradle-wrapper.jar [debian/copyright:*]",
    ),
    (
        "missing-license-paragraph-in-dep5-copyright",
        "artistic *",
        "artistic [debian/copyright:*]",
    ),
    (
        "script-not-executable",
        r"\[etc/lynis/plugins/*",
        r"\[etc/lynis/plugins/*",
    ),
    (
        "source-is-missing",
        "pydata_sphinx_theme/static/js/index.d8bbf5861d671d414e1a.js line length "
        "is 992 characters (>512)",
        "[pydata_sphinx_theme/static/js/index.d8bbf5861d671d414e1a.js]",
    ),
    (
        "very-long-line-length-in-source-file",
        "build/js/bootstrap-tour-standalone.js line length is 587 characters "
        "(>512)",
        "587 > 512 [build/js/bootstrap-tour-standalone.js:*]",
    ),
    ("hardening-no-relro", "usr/lib/libfoo.so", "[usr/lib/libfoo.so]"),
    ("hardening-no-pie", "usr/lib/libfoo.so", "[usr/lib/libfoo.so]"),
    (
        "jar-not-in-usr-share",
        "usr/lib/R/site-library/rJava/jri/JRI.jar",
        "[usr/lib/R/site-library/rJava/jri/JRI.jar]",
    ),
    (
        "package-installs-java-bytecode",
        "usr/lib/R/site-library/rJava/java/ArrayWrapper.class",
        "[usr/lib/R/site-library/rJava/java/ArrayWrapper.class]",
    ),
    (
        "debconf-is-not-a-registry",
        "usr/share/doc/dbconfig-common/examples/config",
        "[usr/share/doc/dbconfig-common/examples/config:*]",
    ),
    (
        "unused-debconf-template",
        "dbconfig-common/app-password-confirm",
        "dbconfig-common/app-password-confirm [*:*]",
    ),
    (
        "apache2-reverse-dependency-calls-invoke-rc.d",
        "postrm:21",
        "[postrm:21]",
    ),
    (
        "application-in-library-section",
        "libs usr/bin/cpan5.32-x86_64-linux-gnu",
        "libs [usr/bin/cpan5.32-x86_64-linux-gnu]",
    ),
    (
        "repeated-path-segment",
        "books usr/lib/acl2-8.4dfsg/books/projects/paco/books/",
        "books [usr/lib/acl2-8.4dfsg/books/projects/paco/books/]",
    ),
    ("symlink-is-self-recursive", ". usr/bin/X11", ". [usr/bin/X11]"),
    (
        "privacy-breach-google-adsense",
        "usr/share/doc/jquery-alternative-doc/index.html "
        '(choke on: "google-analytics.com/ga.js")',
        '(choke on: "google-analytics.com/ga.js") '
        "[usr/share/doc/jquery-alternative-doc/index.html]",
    ),
    (
        "systemd-service-file-refers-to-unusual-wantedby-target",
        "lib/systemd/system/autodir-home.service autodir.service",
        "autodir.service [lib/systemd/system/autodir-home.service]",
    ),
    (
        "groff-message",
        "usr/share/man/man1/connmanctl.1.gz 282: warning [p 4, 6.0i]: "
        "cannot adjust line",
        "282: warning [p 4, 6.0i]: cannot adjust line "
        "[usr/share/man/man1/connmanctl.1.gz:*]",
    ),
    ("spelling-error-in-binary", "wtH with *", "wtH with *"),
    (
        "spelling-error-in-binary",
        "usr/bin/foo wtH with",
        "wtH with [usr/bin/foo]",
    ),
    (
        "duplicate-font-file",
        "usr/lib/R/site-library/rgl/fonts/FreeMono.ttf "
        "also in fonts-freefont-ttf",
        "also in (fonts-freefont-ttf) "
        "[usr/lib/R/site-library/rgl/fonts/FreeMono.ttf]",
    ),
]


class InfoFixerDataTest(TestCase):
    def test_data(self):
        for tag, old_info, expected_info in INFO_FIXER_TESTS:
            got_info = fix_override_info(
                LintianOverride(tag=tag, info=old_info)
            )
            self.assertEqual(
                got_info,
                expected_info,
                f"Unexpected transformation for {tag}: {old_info!r} ⇒ {got_info!r} != {expected_info!r}",
            )
