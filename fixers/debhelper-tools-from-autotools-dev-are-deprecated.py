#!/usr/bin/python3

from lintian_brush.control import (
    ensure_minimum_debhelper_version,
    ControlUpdater,
    )
from lintian_brush.fixer import report_result
from lintian_brush.rules import (
    update_rules,
    dh_invoke_drop_with,
    )


def cb(line, target):
    if line.strip() == b'dh_autotools-dev_updateconfig':
        return []
    if line.strip() == b'dh_autotools-dev_restoreconfig':
        return []
    line = dh_invoke_drop_with(line, b'autotools-dev')
    line = dh_invoke_drop_with(line, b'autotools_dev')
    return line


if update_rules(cb):
    with ControlUpdater() as updater:
        updater.source["Build-Depends"] = ensure_minimum_debhelper_version(
            updater.source.get("Build-Depends", ""), "9.20160114")


report_result(
    "Drop use of autotools-dev debhelper.",
    fixed_lintian_tags=['debhelper-tools-from-autotools-dev-are-deprecated'])
