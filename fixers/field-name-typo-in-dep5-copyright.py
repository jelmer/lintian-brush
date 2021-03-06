#!/usr/bin/python3

from debmutate.deb822 import Deb822Editor
from lintian_brush.fixer import report_result, warn, fixed_lintian_tag
import sys

try:
    from Levenshtein import distance
except ImportError:
    sys.exit(2)

valid_field_names = {
    'Files', 'License', 'Copyright', 'Comment',
    'Upstream-Name', 'Format', 'Upstream-Contact',
    'Source', 'Upstream', 'Contact', 'Name'}

typo_fixed = set()
case_fixed = set()

try:
    with Deb822Editor('debian/copyright') as updater:
        for paragraph in updater.paragraphs:
            for field in paragraph:
                if field in valid_field_names:
                    continue
                if (field.startswith('X-') and
                        field[2:] in valid_field_names):
                    if field[2:] in paragraph:
                        warn('Both %s and %s exist.' % (
                             field, field[2:]))
                        continue
                    value = paragraph[field]
                    del paragraph[field]
                    paragraph[field[2:]] = value
                    typo_fixed.add((field, field[2:]))
                    fixed_lintian_tag(
                        'source', 'field-name-typo-in-dep5-copyright',
                        '%s (line XX)' % field)
                    continue

                for option in valid_field_names:
                    if distance(field, option) == 1:
                        value = paragraph[field]
                        del paragraph[field]
                        paragraph[option] = value
                        if option.lower() == field.lower():
                            case_fixed.add((field, option))
                        else:
                            typo_fixed.add((field, option))
                            fixed_lintian_tag(
                                'source', 'field-name-typo-in-dep5-copyright',
                                '%s (line XX)' % field)
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
    'Fix field name %s in debian/copyright (%s).' % (kind, fixed_str))
