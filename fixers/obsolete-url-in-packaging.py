#!/usr/bin/python3

from lintian_brush.fixer import control, LintianIssue, report_result
from lintian_brush.lintian import is_obsolete_site
from urllib.parse import urlparse


with control:
    homepage = control.source.get('Homepage')
    if homepage is not None and is_obsolete_site(urlparse(homepage)):
        issue = LintianIssue(
            control.source, 'obsolete-url-in-packaging', 'debian/control')
        if issue.should_fix():
            issue.report_fixed()
            del control.source['Homepage']


# TODO(jelmer): Check debian/copyright
# TODO(jelmer): Check debian/watch


report_result('Drop fields with obsolete URLs.')
