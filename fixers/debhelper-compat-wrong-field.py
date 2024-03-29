#!/usr/bin/python3

from debmutate.control import (
    add_dependency,
    drop_dependency,
    get_relation,
)

from lintian_brush.fixer import control, report_result

with control as updater:
    try:
        pos, old = get_relation(
            updater.source.get("Build-Depends-Indep", ""), "debhelper-compat"
        )
    except KeyError:
        pass
    else:
        updater.source["Build-Depends"] = add_dependency(
            updater.source.get("Build-Depends", ""), old
        )
        updater.source["Build-Depends-Indep"] = drop_dependency(
            updater.source.get("Build-Depends-Indep", ""), "debhelper-compat"
        )
        if not updater.source["Build-Depends-Indep"].strip():
            del updater.source["Build-Depends-Indep"]


report_result(
    "Move debhelper-compat from Build-Depends-Indep to Build-Depends."
)
