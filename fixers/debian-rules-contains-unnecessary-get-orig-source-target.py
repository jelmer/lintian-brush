#!/usr/bin/python3

import os
import sys
from contextlib import suppress

from debmutate._rules import RulesEditor

from lintian_brush.fixer import LintianIssue, opinionated, report_result

certainty = None

if not opinionated() and os.listdir() == ["debian"]:
    # See https://salsa.debian.org/debian-ayatana-team/\
    # snapd-glib/-/merge_requests/6#note_358358
    sys.exit(0)

with suppress(FileNotFoundError), RulesEditor() as updater:
    for rule in updater.makefile.iter_rules(b"get-orig-source"):
        commands = rule.commands()
        if [b"uscan"] == [c.split(b" ")[0] for c in commands]:
            certainty = "certain"
        else:
            certainty = "possible"
        issue = LintianIssue(
            "source",
            "debian-rules-contains-unnecessary-get-orig-source-target",
            "",
        )
        if issue.should_fix():
            rule.clear()
            updater.makefile.drop_phony(b"get-orig-source")
            issue.report_fixed()


report_result(
    "Remove unnecessary get-orig-source-target.", certainty=certainty
)
