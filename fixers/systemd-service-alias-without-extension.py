#!/usr/bin/python3

from lintian_brush.fixer import report_result, fixed_lintian_tag
from lintian_brush.systemd import systemd_service_files, SystemdServiceEditor
import os

for path in systemd_service_files():
    base, required_ext = os.path.splitext(path)
    with SystemdServiceEditor(path) as updater:
        for i, alias in enumerate(updater.file['Unit']['Alias']):
            base, ext = os.path.splitext(alias)
            if ext != required_ext:
                updater.file['Unit']['Alias'][i] = base + required_ext
                fixed_lintian_tag(
                    'source',
                    'systemd-service-alias-without-extension',
                    '%s' % path)


report_result('Use proper extensions in Alias in systemd files.')
