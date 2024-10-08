#!/usr/bin/python3
import os
import sys

from debmutate.watch import WatchFile

from lintian_brush.fixer import (
    LintianIssue,
    current_package_version,
    net_access_allowed,
    package_is_native,
    report_result,
)
from lintian_brush.watch import (
    find_candidates,
)

if os.path.exists("debian/watch") or package_is_native():
    # Nothing to do here..
    sys.exit(0)

issue = LintianIssue("source", "debian-watch-file-is-missing", info="")

if not issue.should_fix():
    sys.exit(0)

candidates = []

good_upstream_versions = {current_package_version().upstream_version}

candidates = find_candidates(
    ".", good_upstream_versions, net_access=net_access_allowed()
)


# TODO(jelmer): parse cabal file and call candidates_from_hackage

if not candidates:
    sys.exit(0)

winner = candidates[0]

wf = WatchFile()
wf.entries.append(winner.watch)

with open("debian/watch", "w") as f:
    wf.dump(f)
    issue.report_fixed()

report_result(
    f"Add debian/watch file, using {winner.site}.",
    certainty=winner.certainty,
)
