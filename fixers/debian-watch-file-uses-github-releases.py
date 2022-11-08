#!/usr/bin/python3

from debmutate.watch import WatchEditor

from lintian_brush.fixer import (
    report_result, source_package_name, current_package_version,
)
from lintian_brush.watch import fix_github_releases, watch_entries_certainty


with WatchEditor() as updater:
    entries = fix_github_releases(updater)
    certainty = watch_entries_certainty(entries, source_package_name(),
        expected_versions=[current_package_version().upstream_version])


report_result(
    "debian/watch: Use GitHub /tags rather than /releases page.",
    certainty=certainty)
