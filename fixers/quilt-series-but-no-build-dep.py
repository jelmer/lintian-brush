#!/usr/bin/python3

import os
from typing import Optional

from lintian_brush.control import ensure_some_version, ControlUpdater
from lintian_brush.fixer import report_result

format: Optional[str]
try:
    with open('debian/source/format', 'r') as f:
        format = f.read().strip()
except FileNotFoundError:
    format = None

if format != '3.0 (quilt)' and os.path.exists('debian/patches/series'):
    with ControlUpdater() as updater:
        updater.source['Build-Depends'] = ensure_some_version(
            updater.source['Build-Depends'], 'quilt')


report_result(
    'Add missing dependency on quilt.',
    fixed_lintian_tags=['quilt-series-but-no-build-dep'])
