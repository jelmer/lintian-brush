#!/usr/bin/python3

import os

try:
    with open('debian/tests/control', 'r') as f:
        if f.read().strip() == '':
            os.unlink('debian/tests/control')
except FileNotFoundError:
    pass

print('Remove empty debian/tests/control.')
print('Fixed-Lintian-Tags: empty-debian-tests-control')
