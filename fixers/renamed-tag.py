#!/usr/bin/python3

from lintian_brush.fixer import report_result, LintianIssue
from lintian_brush.lintian_overrides import (
    update_overrides,
    LintianOverride,
    load_renamed_tags,
    )


renames = load_renamed_tags()


def rename_override_tags(lineno, override):
    try:
        new_tag = renames[override.tag]
    except KeyError:
        pass  # no rename
    else:
        issue = LintianIssue(
            (override.type, override.package), 'renamed-tag',
            '%s => %s' % (override.tag, new_tag))
        if issue.should_fix():
            issue.report_fixed()
            return LintianOverride(
                package=override.package, archlist=override.archlist,
                type=override.type, tag=new_tag,
                info=override.info)
    return override


update_overrides(rename_override_tags)

report_result("Update renamed lintian tag names in lintian overrides.")
