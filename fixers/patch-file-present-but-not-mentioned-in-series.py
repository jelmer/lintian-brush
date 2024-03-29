#!/usr/bin/python3

import os
import sys

from lintian_brush.fixer import (
    LintianIssue,
    opinionated,
    report_result,
)
from lintian_brush.patches import read_quilt_series

if not opinionated():
    # In a lot of cases, it seems like removing the patch is not the right
    # thing to do.
    sys.exit(0)

try:
    patches = set()
    with open("debian/patches/series", "rb") as f:
        for patch, _quoted, _options in read_quilt_series(f):
            patches.add(patch)
except FileNotFoundError:
    sys.exit(0)

removed = set()

for patch in os.listdir("debian/patches"):
    path = os.path.join("debian", "patches", patch)
    # Don't delete the series file
    if patch in ("series", "00list"):
        continue
    # Ignore everything that is not a regular file
    if not os.path.isfile(path):
        continue
    # Ignore any README files
    if patch.startswith("README"):
        continue
    # Ignore any notes files
    if patch.startswith("notes"):
        continue
    # Ignore everything that is listed in series
    if patch in patches:
        continue
    issue = LintianIssue(
        "source", "patch-file-present-but-not-mentioned-in-series", patch
    )
    if not issue.should_fix():
        continue
    removed.add(patch)
    os.unlink(path)
    issue.report_fixed()


description = (
    "Remove patch{} {} that {} missing from debian/patches/series.".format(
        "es" if len(removed) > 1 else "",
        ", ".join(sorted(removed)),
        "is" if len(removed) == 1 else "are",
    )
)
report_result(description)
