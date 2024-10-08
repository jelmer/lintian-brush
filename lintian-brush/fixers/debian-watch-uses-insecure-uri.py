#!/usr/bin/python3

import os
import subprocess
import sys

from debmutate.watch import parse_watch_file

from lintian_brush.fixer import (
    LintianIssue,
    net_access_allowed,
    report_result,
)

if not os.path.exists("debian/watch"):
    sys.exit(0)


def watchfile_has_http():
    with open("debian/watch") as f:
        wf = parse_watch_file(f)

    if not wf:
        return False

    for entry in wf:
        if entry.url.startswith("http://"):
            return True
    else:
        # No plain HTTP URLs
        return False


def update_watchfile(fn):
    with open("debian/watch") as f:
        old = f.readlines()

    new = []
    for line in old:
        try:
            (bef, aft) = line.split("#", 1)
        except ValueError:
            bef = line
            aft = None
        newbef = fn(bef)
        if newbef != bef:
            issue = LintianIssue(
                "source", "debian-watch-uses-insecure-uri", bef
            )
            if issue.should_fix():
                if aft is not None:
                    new.append("#".join([newbef, aft]))
                else:
                    new.append(newbef)
                issue.report_fixed()
            else:
                new.append(line)
        else:
            new.append(line)

    if old != new:
        with open("debian/watch", "w") as f:
            f.writelines(new)
        return True
    return False


if not watchfile_has_http():
    sys.exit(0)


# We hardcode the replacements for some sites, since these testsuite uses
# these. The method below (involving uscan) doesn't work from e.g. sbuild
# hosts.
def stock_replace(line):
    for hostname in ["code.launchpad.net", "launchpad.net", "ftp.gnu.org"]:
        line = line.replace(f"http://{hostname}/", f"https://{hostname}/")
    return line


update_watchfile(stock_replace)


report_result("Use secure URI in debian/watch.")


if not watchfile_has_http():
    sys.exit(0)


if not net_access_allowed():
    sys.exit(0)


def run_uscan_dehs():
    return subprocess.check_output(
        ["uscan", "--dehs", "--report"], stderr=subprocess.PIPE
    )


try:
    before = run_uscan_dehs()
except subprocess.CalledProcessError:
    # Before doesn't work :(
    sys.exit(0)


def replace_all(line):
    return line.replace("http://", "https://")


if not update_watchfile(replace_all):
    sys.exit(0)

try:
    after = run_uscan_dehs()
except subprocess.CalledProcessError:
    sys.exit(2)

# uscan creates backup files.
for path in [
    "debian/upstream/signing-key.pgp.backup",
    "debian/upstream-signing-key.pgp.backup",
]:
    if os.path.exists(path):
        os.unlink(path)

# Make sure that reports are same up to http/https substitution in URL.
if before.replace(b"http://", b"https://") != after:
    # Couldn't do anything :(
    sys.exit(2)
