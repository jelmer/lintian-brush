#!/usr/bin/python3

from debmutate.control import (
    ControlEditor,
    )
from debmutate.debhelper import (
    ensure_minimum_debhelper_version,
    )
from lintian_brush.fixer import (
    report_result,
    fixed_lintian_tag,
    )
from lintian_brush.rules import (
    update_rules,
    dh_invoke_drop_with,
    )


def cb(line, target):
    if line.strip() == b'dh_autotools-dev_updateconfig':
        fixed_lintian_tag(
            'source', 'debhelper-tools-from-autotools-dev-are-deprecated',
            info='dh_autotools-dev_updateconfig')
        return []
    if line.strip() == b'dh_autotools-dev_restoreconfig':
        fixed_lintian_tag(
            'source', 'debhelper-tools-from-autotools-dev-are-deprecated',
            info='dh_autotools-dev_restoreconfig')
        return []
    newline = dh_invoke_drop_with(line, b'autotools-dev')
    if newline != line:
        fixed_lintian_tag(
            'source', 'debhelper-tools-from-autotools-dev-are-deprecated',
            info='dh ... --with autotools-dev')
        line = newline
    newline = dh_invoke_drop_with(line, b'autotools_dev')
    if newline != line:
        fixed_lintian_tag(
            'source', 'debhelper-tools-from-autotools-dev-are-deprecated',
            info='dh ... --with autotools_dev')
        line = newline
    return line


if update_rules(cb):
    with ControlEditor() as updater:
        ensure_minimum_debhelper_version(updater.source, "9.20160114")


report_result("Drop use of autotools-dev debhelper.")
