#!/usr/bin/python3
from lintian_brush.control import update_control
import sys
import urllib.parse
def add_vcs_browser(control):
    if "Vcs-Browser" in control:
        return
    try:
        vcs_git = control["Vcs-Git"]
    except KeyError:
        return
    parsed = urllib.parse.urlparse(vcs_git)
    if parsed.netloc in ('github.com', 'salsa.debian.org'):
        control["Vcs-Browser"] = urllib.parse.urlunparse(('https', ) + parsed[1:])


update_control(source_package_cb=add_vcs_browser)
print("debian/control: Add Vcs-Browser field")
print("Fixed-Lintian-Tags: missing-vcs-browser-field")
