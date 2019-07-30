#!/usr/bin/python3
from debian.changelog import Version
import sys

from lintian_brush.control import (
    drop_dependency,
    ensure_minimum_version,
    update_control,
    )
from lintian_brush.rules import (
    dh_invoke_drop_with,
    update_rules,
    )


def bump_debhelper(control):
    control["Build-Depends"] = ensure_minimum_version(
        control["Build-Depends"],
        "debhelper", Version("10"))
    control["Build-Depends"] = drop_dependency(
        control["Build-Depends"],
        "dh-autoreconf")


def drop_with_autoreconf(line):
    return dh_invoke_drop_with(line, b'autoreconf')


changed = update_rules(drop_with_autoreconf)
if not changed:
    sys.exit(2)


update_control(source_package_cb=bump_debhelper)

print("Drop unnecessary dependency on dh-autoconf.")
print("Fixed-Lintian-Tags: useless-autoreconf-build-depends")
