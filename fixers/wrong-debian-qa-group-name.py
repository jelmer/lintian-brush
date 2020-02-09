#!/usr/bin/python3

from lintian_brush.control import ControlUpdater
from email.utils import parseaddr

QA_MAINTAINER = "Debian QA Group <packages@qa.debian.org>"

with ControlUpdater() as updater:
    try:
        email = parseaddr(updater.source["Maintainer"])[1]
    except KeyError:
        # No maintainer? Weird, but sure.
        pass
    else:
        if email == "packages@qa.debian.org":
            updater.source["Maintainer"] = QA_MAINTAINER

print("Fix Debian QA group name.")
print("Fixed-Lintian-Tags: wrong-debian-qa-group-name")
