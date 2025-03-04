#!/usr/bin/python3

import re
import sys

from debmutate.copyright import CopyrightEditor, NotMachineReadableError

from lintian_brush.fixer import LintianIssue, report_result

used = []
defined = set()
certainty = "certain"


def extract_licenses(synopsis):
    """Extract license names from a synopsis.

    This will return a list of licenses, as a list of possible names per
    license.
    """
    ret = []
    for license in synopsis.split(" or "):
        options = [license]
        m = re.fullmatch(r"(.*) with (.*) exception", license)
        if m:
            license = m.group(1)
        options.append(license)
        ret.append(options)
    return ret


try:  # noqa: C901
    with CopyrightEditor() as updater:
        if (
            updater.copyright.header.license
            and updater.copyright.header.license.text
        ):
            defined.add(updater.copyright.header.license.synopsis)
        for paragraph in updater.copyright.all_paragraphs():
            if not paragraph.license:
                continue
            if paragraph.license.text:
                defined.add(paragraph.license.synopsis)

        if updater.copyright.header.license:
            synopsis = updater.copyright.header.license.synopsis
            if synopsis:
                if synopsis in defined:
                    used.append([synopsis])
                used.extend(extract_licenses(synopsis))

        for paragraph in updater.copyright.all_files_paragraphs():
            if not paragraph.license:
                continue
            if paragraph.files:
                synopsis = paragraph.license.synopsis
                if synopsis in defined:
                    used.append([synopsis])
                used.extend(extract_licenses(synopsis))

        extra_defined = set(defined)
        for options in used:
            extra_defined -= set(options)

        extra_used = []
        for options in used:
            for option in options:
                if option in defined:
                    break
            else:
                extra_used.append(options)

        if extra_used:
            sys.stderr.write(
                "Undefined licenses in copyright: %r"
                % [options[0] for options in extra_used]
            )
            # Drop the certainty since it's possible the undefined licenses
            # are actually the referenced ones.
            certainty = "possible"

        for name in extra_defined:
            for paragraph in updater.copyright.all_paragraphs():
                if not paragraph.license:
                    continue
                if paragraph.license.synopsis == name:
                    continue
                if paragraph.license.text and name in paragraph.license.text:
                    certainty = "possible"
                if paragraph.comment and name in paragraph.comment:
                    certainty = "possible"

        if extra_defined and not extra_used:
            for paragraph in list(updater.copyright.all_paragraphs()):
                if not paragraph.license:
                    continue
                issue = LintianIssue(
                    "source",
                    "unused-license-paragraph-in-dep5-copyright",
                    info=paragraph.license.synopsis.lower(),
                )
                if not issue.should_fix():
                    continue
                if paragraph.license.synopsis in extra_defined:
                    issue.report_fixed()
                    updater.remove(paragraph)
except (FileNotFoundError, NotMachineReadableError):
    pass
else:
    report_result(
        "Remove unused license definitions for {}.".format(
            ", ".join(extra_defined)
        ),
        certainty=certainty,
    )
