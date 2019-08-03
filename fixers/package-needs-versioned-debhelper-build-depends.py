#!/usr/bin/python3

import sys
from lintian_brush.control import (
    ensure_minimum_version,
    get_relation,
    update_control,
    )


def bump_debhelper(control):
    try:
        get_relation(control["Build-Depends"], "debhelper-compat")
    except KeyError:
        pass
    else:
        return
    control["Build-Depends"] = ensure_minimum_version(
            control["Build-Depends"],
            "debhelper",
            "%s~" % minimum_version)

# Debian source package is not obliged to contain `debian/compat'.
# Firstly, it may not use debhelper; secondly it may use modern
# `debhelper-compat' dependency style.


try:
    with open('debian/compat', 'r') as f:
        minimum_version = f.read().strip()
except FileNotFoundError:
    sys.exit(0)

update_control(source_package_cb=bump_debhelper)

print("Bump debhelper dependency to >= %s, since that's what is "
      "used in debian/compat." % minimum_version)
print("Fixed-Lintian-Tags: package-needs-versioned-debhelper-build-depends")
