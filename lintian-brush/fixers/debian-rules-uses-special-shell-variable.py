#!/usr/bin/python3

from contextlib import suppress

from debmutate.reformatting import check_generated_file

from lintian_brush.fixer import LintianIssue, report_result
from lintian_brush.line_editor import LineEditor

check_generated_file("debian/rules")

with suppress(FileNotFoundError), LineEditor("debian/rules", "b") as e:
    for lineno, line in e:
        newline = line.replace(
            b"$(dir $(_))", b"$(dir $(firstword $(MAKEFILE_LIST)))"
        )
        if newline != line:
            issue = LintianIssue(
                "source",
                "debian-rules-uses-special-shell-variable",
                info=f"line {lineno}"
            )
            if issue.should_fix():
                e[lineno] = newline
                issue.report_fixed()


report_result("Avoid using $(_) to discover source package directory.")
