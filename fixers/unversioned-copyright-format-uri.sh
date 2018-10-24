#!/bin/sh
perl -p -i -e 's/^(Format|Format-Specification): .*/Format: https:\/\/www.debian.org\/doc\/packaging-manuals\/copyright-format\/1.0\//' debian/copyright
echo "Use versioned copyright format URI."
echo "Fixed-Lintian-Tags: unversioned-copyright-format-uri"
