#!/usr/bin/python3

from lintian_brush.control import get_debhelper_compat_version
from lintian_brush.rules import (
    dh_invoke_drop_argument,
    dh_invoke_drop_with,
    update_rules,
    )

removed_args = []
unnecessary_args = []
unnecessary_with = []


compat_version = get_debhelper_compat_version()
if compat_version and compat_version >= 10:
    unnecessary_args.append(b'--parallel')
    unnecessary_with.append(b'systemd')


def drop_unnecessary_args(line, target):
    if not line.startswith(b'dh ') and not line.startswith(b'dh_'):
        return line
    for arg in unnecessary_args:
        newline = dh_invoke_drop_argument(line, arg)
        if newline != line:
            removed_args.append(arg)
            line = newline
    for arg in unnecessary_with:
        newline = dh_invoke_drop_with(line, arg)
        if newline != line:
            removed_args.append(b'--with=%s' % arg)
            line = newline
    return line


update_rules(drop_unnecessary_args)

print('Drop unnecessary dh arguments: %s' %
      ', '.join([arg.decode() for arg in removed_args]))
print('Fixed-Lintian-Tags: debian-rules-uses-unnecessary-dh-argument')
