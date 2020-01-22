#!/usr/bin/python3
from lintian_brush.control import update_control
from lintian_brush.fixer import report_result
fields = []
packages = []


def rm_empty_field(control):
    for k, v in control.items():
        if not v.strip():
            fields.append(k)
            if control.get("Package"):
                packages.append(control.get("Package"))
            del control[k]


update_control(source_package_cb=rm_empty_field,
               binary_package_cb=rm_empty_field)

report_result(
    "debian/control: Remove empty control field%s %s%s." % (
     "s" if len(fields) > 1 else "",
     ", ".join(fields),
     (" in package %s" % ', '.join(packages)) if packages else "",
    ),
    fixed_lintian_tags=['debian-control-has-empty-field'])
