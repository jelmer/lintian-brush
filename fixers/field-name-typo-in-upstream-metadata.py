#!/usr/bin/python3

from lintian_brush.yaml import YamlUpdater
from lintian_brush.fixer import report_result, warn
import sys

try:
    from Levenshtein import distance
except ImportError:
    sys.exit(2)

valid_field_names = {
    'Archive',
    'ASCL-Id',
    'Bug-Database',
    'Bug-Submit',
    'Cite-As',
    'Changelog',
    'CPE',
    'Documentation',
    'Donation',
    'FAQ',
    'Funding',
    'Gallery',
    'Other-References',
    'Reference',
    'Registration',
    'Registry',
    'Repository',
    'Repository-Browse',
    'Screenshots',
    'Security-Contact',
    'Webservice',
}

typo_fixed = set()
case_fixed = set()

try:
    with YamlUpdater('debian/upstream/metadata') as updater:
        for field in updater.code:
            if field in valid_field_names:
                continue
            if (field.startswith('X-') and
                    field[2:] in valid_field_names):
                if field[2:] in updater.code:
                    warn('Both %s and %s exist.' % (
                         field, field[2:]))
                    continue
                value = updater.code[field]
                del updater.code[field]
                updater.code[field[2:]] = value
                typo_fixed.add((field, field[2:]))
                continue

            for option in valid_field_names:
                if distance(field, option) == 1:
                    value = updater.code[field]
                    del updater.code[field]
                    updater.code[option] = value
                    if option.lower() == field.lower():
                        case_fixed.add((field, option))
                    else:
                        typo_fixed.add((field, option))
                    break
except FileNotFoundError:
    pass


if case_fixed:
    kind = 'case' + ('s' if len(case_fixed) > 1 else '')
else:
    kind = ''
if typo_fixed:
    if case_fixed:
        kind += ' and '
    kind += 'typo' + ('s' if len(typo_fixed) > 1 else '')

fixed_str = ', '.join(
    ['%s => %s' % (old, new)
     for (old, new) in sorted(list(case_fixed) + list(typo_fixed))])

report_result(
    'Fix field name %s in debian/upstream/metadata (%s).' % (kind, fixed_str))
