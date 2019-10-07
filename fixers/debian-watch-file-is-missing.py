#!/usr/bin/python3
import os
import subprocess
import sys

from lintian_brush.watch import WatchFile, Watch


if os.path.exists('debian/watch'):
    # Nothing to do here..
    sys.exit(0)

watch_contents = None
site = None
wf = WatchFile()
if os.path.exists('setup.py'):
    try:
        lines = subprocess.check_output(
            ['python3', 'setup.py', '--name', '--version']).splitlines()
    except subprocess.CalledProcessError:
        # Worth a shot..
        lines = subprocess.check_output(
            ['python2', 'setup.py', '--name', '--version']).splitlines()
    lines = [line for line in lines if not line.startswith(b'W: ')]
    (project, version) = lines
    # TODO(jelmer): verify that <name>-<version> appears on
    # https://pypi.python.org/simple/<name>
    # TODO(jelmer): download watch file from
    # http://pypi.debian.net/<project>/watch
    url = (r'https://pypi.debian.net/%(project)s/%(project)'
           r's-(.+)\.(?:zip|tgz|tbz|txz|(?:tar\.(?:gz|bz2|xz)))' % {
            'project': project.decode()})
    w = Watch(url, opts=[
        'uversionmangle=s/(rc|a|b|c)/~$1/', 'pgpsigurlmangle=s/$/.asc/'])
    wf.entries.append(w)
    site = "pypi"

if not wf.entries:
    sys.exit(0)

with open('debian/watch', 'w') as f:
    wf.dump(f)

print("Add debian/watch file, using %s." % site)
print("Certainty: possible")
print("Fixed-Lintian-Tags: debian-watch-file-is-missing")
