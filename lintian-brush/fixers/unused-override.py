#!/usr/bin/python3

import sys

try:
    import psycopg2  # noqa: F401
except ModuleNotFoundError:
    sys.exit(2)

from lintian_brush.fixer import (
    control,
    diligence,
    fixed_lintian_tag,
    net_access_allowed,
    report_result,
)
from lintian_brush.lintian_overrides import remove_unused

INTERMITTENT_LINTIAN_TAGS = [
    "rc-version-greater-than-expected-version",
]


if diligence() < 1:
    # Removing unused overrides requires pro-actively contacting UDD.
    sys.exit(0)

if not net_access_allowed():
    sys.exit(0)

removed = remove_unused(
    control.paragraphs, ignore_tags=INTERMITTENT_LINTIAN_TAGS
)

description = [
    f"Remove {len(removed)} unused lintian overrides.\n"
    "\n",
]
for override in removed:
    description.append(f"* {override.tag}\n")
    fixed_lintian_tag(
        "source",
        "unused-override",
        info=(override.tag, override.info if override.info else ""),
    )

report_result("".join(description), certainty="certain")
