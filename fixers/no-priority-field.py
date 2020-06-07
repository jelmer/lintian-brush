#!/usr/bin/python3

from debmutate.control import ControlUpdater
from lintian_brush.fixer import report_result

import sys

# TODO(jelmer): Support unknown-priority tag

certainty = 'certain'
updated = {}

with ControlUpdater() as updater:
    if updater.source.get('Priority'):
        sys.exit(0)
    binary_priorities = set()
    for binary in updater.binaries:
        if not binary.get('Priority'):
            # TODO(jelmer): Check if all dependencies are priority standard or
            # important and if they are, consider bump the priority or not
            # setting the priority at all?
            binary['Priority'] = 'optional'
            certainty = 'confident'
            updated[binary['Package']] = binary['Priority']
        if binary.get('Priority'):
            binary_priorities.add(binary['Priority'])
    if len(binary_priorities) == 1:
        updater.source['Priority'] = binary_priorities.pop()
        for binary in updater.binaries:
            try:
                del binary['Priority']
            except KeyError:
                pass
        report_result(
            'Set priority in source stanza, since it is the same '
            'for all packages.',
            certainty='confident',
            fixed_lintian_tags=(['no-priority-field'] if updated else []))
    elif updated:
        report_result(
            'Set priority for binary packages %s.' % (
                ['%s (%s)' % item for item in updated.items()]),
            fixed_lintian_tags=['no-priority-field'])
