#!/usr/bin/python3

from datetime import datetime, timedelta
import os
import email.utils
import sys

from debmutate.changelog import ChangelogEditor
from debmutate.debhelper import MaintscriptEditor
from lintian_brush.debhelper import drop_obsolete_maintscript_entries
from lintian_brush.fixer import report_result, upgrade_release, warn


# If there is no information from the upgrade release, default to 5 years.
DEFAULT_AGE_THRESHOLD_DAYS = 5 * 365


maintscripts = []
for entry in os.scandir('debian'):
    if not (entry.name == "maintscript" or entry.name.endswith(".maintscript")):
        continue
    maintscripts.append(entry.name)


# Determine the date for which versions created then should still be supported.
# This is a little bit tricky since versions uploaded at a particular date
# may not have made it into the release then.
from distro_info import DebianDistroInfo  # noqa: E402
try:
    [release] = [
        r for r in DebianDistroInfo().get_all('object')
        if r.codename.lower() == upgrade_release()]
except ValueError:
    date_threshold = None
else:
    date_threshold = release.release

if date_threshold is None:
    # Release has not yet or will never be released
    # Default to 5 years
    date_threshold = (datetime.now() - timedelta(days=DEFAULT_AGE_THRESHOLD_DAYS)).date()


cl_dates = []
with ChangelogEditor() as cl:
    for block in cl:
        try:
            dt = email.utils.parsedate_to_datetime(block.date)
        except (TypeError, ValueError):
            warn('Invalid date %r for %s' % (block.date, block.version))
            # parsedate_to_datetime is buggy and raises a TypeError
            # when the date is invalid.
            # We can't reliably check anymore :(
            sys.exit(2)
        cl_dates.append((block.version, dt))


def is_long_passed(version):
    for (cl_version, cl_dt) in cl_dates:
        if cl_version <= version and cl_dt.date() > date_threshold:
            return False
    return True


total_entries = 0
ret = []
for name in maintscripts:
    with MaintscriptEditor(os.path.join('debian', name)) as editor:
        removed = drop_obsolete_maintscript_entries(
            editor, lambda p, v: is_long_passed(v))
        if removed:
            ret.append((os.path.join('debian', name), removed))
            total_entries += len(removed)

if total_entries == 1:
    report_result('Remove %d obsolete maintscript entry.' % total_entries)
else:
    report_result('Remove %d obsolete maintscript entries in %d files.' %
                  (total_entries, len(ret)))
