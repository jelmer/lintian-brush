#!/usr/bin/python3

from lintian_brush.lintian_overrides import remove_unused

removed = remove_unused()

print('Remove %d unused lintian overrides.' % len(removed))
print('Fixed-Lintian-Tags: unused-override')
print('Certainty: certain')
