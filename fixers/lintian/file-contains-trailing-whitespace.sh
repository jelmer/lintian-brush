#!/bin/sh
sed -i -e 's@[[:space:]]*$@@g' debian/control* debian/changelog
echo "Trim trailing whitespace."
echo "Fixed-Lintian-Tags: file-contains-trailing-whitespace"
