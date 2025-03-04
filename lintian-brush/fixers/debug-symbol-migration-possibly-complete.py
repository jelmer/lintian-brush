#!/usr/bin/python3

import os
import re
import sys
from contextlib import suppress

from debmutate._rules import RulesEditor, discard_pointless_override

from debian.deb822 import PkgRelation
from lintian_brush.fixer import (
    LintianIssue,
    compat_release,
    net_access_allowed,
    report_result,
)

compat_release = compat_release()


def previous_release(release):
    import distro_info

    debian = distro_info.DebianDistroInfo()
    if release in (debian.devel(), debian.testing(), "experimental"):
        return debian.stable()
    releases = debian.get_all()
    with suppress(ValueError):
        return releases[releases.index(release) - 1]
    # TODO(jelmer): Ubuntu?
    return None


VERSION_CMP_SQL = {
    "=": "=",
    ">=": ">=",
    "<=": "<=",
    ">>": ">",
    "<<": "<",
}


def package_exists(package, release, version_info):
    if not net_access_allowed():
        try:
            return package in os.environ[f"{release.upper()}_PACKAGES"].split(
                ","
            )
        except KeyError:
            return None
    try:
        from lintian_brush.udd import connect_udd_mirror
    except ModuleNotFoundError:
        return None
    with connect_udd_mirror() as udd:
        query = "SELECT True FROM packages WHERE release = %s AND package = %s"
        args = [release, package]
        if version_info is not None:
            version_cmp, version = version_info
            query += f" AND version {VERSION_CMP_SQL[version_cmp]} $3"
            args.append(version)
        with udd.cursor() as cursor:
            cursor.execute(query, tuple(args))
            row = cursor.fetchone()
            return bool(row)


def migration_done(rels):
    previous = previous_release(compat_release)
    if previous is None:
        # We can't determine if the migration is done
        return False
    for rel in rels:
        if len(rel) > 1:
            # Not sure how to handle | Replaces
            return False
        if (
            package_exists(rel[0]["name"], previous, rel[0]["version"])
            is not False
        ):
            return False
    return True


def eliminate_dbgsym_migration(line, target):
    if not line.startswith(b"dh_strip"):
        return line

    def rep_dbgsym_migration(m):
        rep = m.group(2).strip(b'"').strip(b"'").decode()
        if "$" in rep:
            # too complicated
            return m.group(0)
        rep = PkgRelation.parse_relations(rep)
        if migration_done(rep):
            issue = LintianIssue(
                "source",
                "debug-symbol-migration-possibly-complete",
                f"{m.group(0).decode().strip()} (line XX)",
            )
            if issue.should_fix():
                issue.report_fixed()
                return b""
        return m.group(0)

    line = re.sub(
        b"([ \t]+)--dbgsym-migration[= ]('[^']+'|\"[^\"]+\"|[^ ]+)",
        rep_dbgsym_migration,
        line,
    )

    if line == b"dh_strip || dh_strip":
        line = b"dh_strip"

    return line


if not os.path.exists("debian/rules"):
    sys.exit(2)
with RulesEditor() as editor:
    for rule in editor.makefile.iter_all_rules():
        newlines = []
        for line in list(rule.lines[1:]):
            if line.startswith(b"\t"):
                ret = eliminate_dbgsym_migration(line[1:], rule.target)
                newlines.append(b"\t" + ret)
            else:
                newlines.append(line)
        if rule.lines[1:] != newlines:
            rule.lines = [rule.lines[0]] + newlines
            discard_pointless_override(
                editor.makefile, rule, ignore_comments=True
            )


report_result("Drop transition for old debug package migration.")
