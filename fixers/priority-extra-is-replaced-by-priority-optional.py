#!/usr/bin/python3

from lintian_brush.control import ControlUpdater


with ControlUpdater() as updater:
    for para in updater.paragraphs:
        if para.get("Priority") == "extra":
            para["Priority"] = "optional"


print("Change priority extra to priority optional.")
print("Fixed-Lintian-Tags: priority-extra-is-replaced-by-priority-optional")
