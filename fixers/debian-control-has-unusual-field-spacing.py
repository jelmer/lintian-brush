#!/usr/bin/python3

from lintian_brush.reformatting import (
    check_generated_file,
    GeneratedFile,
    )


def rewrite_line(line):
    if not line.split(b'#', 1)[0].strip():
        return line
    if line.startswith(b' ') or line.startswith(b'\t'):
        return line
    (key, value) = line.split(b':', 1)
    if not value.strip():
        return line
    return b'%s: %s\n' % (key, value.lstrip().rstrip(b'\n'))


def fix_field_spacing(path):
    lines = []
    changed = False
    with open(path, 'rb') as f:
        for oldline in f:
            newline = rewrite_line(oldline)
            if newline != oldline:
                changed = True
            lines.append(newline)
    if not changed:
        return False
    with open(path, 'wb') as f:
        f.writelines(lines)
    return True


try:
    check_generated_file('debian/control')
except GeneratedFile as e:
    if e.template_path:
        changed = fix_field_spacing(e.template_path)
        if changed:
            fix_field_spacing('debian/control')
    else:
        raise
else:
    changed = fix_field_spacing('debian/control')

if changed:
    print('Strip unusual field spacing from debian/control.')
    print('Fixed-Lintian-Tags: debian-control-has-unusual-field-spacing')
