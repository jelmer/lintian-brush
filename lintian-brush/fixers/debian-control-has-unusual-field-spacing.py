#!/usr/bin/python3

import sys

from debmutate.control import (
    guess_template_type,
)
from debmutate.reformatting import (
    GeneratedFile,
    check_generated_file,
)

from lintian_brush.fixer import LintianIssue, report_result
from lintian_brush.line_editor import LineEditor


def rewrite_line(line):
    if not line.split(b"#", 1)[0].strip():
        return line
    if line.startswith(b" ") or line.startswith(b"\t"):
        return line
    (key, value) = line.split(b":", 1)
    if not value.strip():
        return line
    return b"%s: %s\n" % (key, value.lstrip().rstrip(b"\n"))


def fix_field_spacing(path):
    changed = False
    with LineEditor(path, "b") as e:
        for lineno, oldline in e:
            newline = rewrite_line(oldline)
            if newline != oldline:
                if path == "debian/control":
                    issue = LintianIssue(
                        "source",
                        "debian-control-has-unusual-field-spacing",
                        info=f"line {lineno}"
                    )
                    if issue.should_fix():
                        e[lineno] = newline
                        changed = True
                        issue.report_fixed()
                else:
                    e[lineno] = newline
                    changed = True
    return changed


try:
    check_generated_file("debian/control")
except GeneratedFile as e:
    if e.template_path:
        template_type = guess_template_type(e.template_path, "debian")
        if template_type is None:
            raise
        changed = fix_field_spacing(e.template_path)
        if changed:
            fix_field_spacing("debian/control")
    else:
        raise
except FileNotFoundError:
    sys.exit(0)
else:
    try:
        changed = fix_field_spacing("debian/control")
    except FileNotFoundError:
        sys.exit(0)

if changed:
    report_result("Strip unusual field spacing from debian/control.")
