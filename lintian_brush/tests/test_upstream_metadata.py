#!/usr/bin/python
# Copyright (C) 2019 Jelmer Vernooij
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for lintian_brush.upstream_metadata."""

from breezy.tests import (
    TestCase,
    TestCaseWithTransport,
    )


from lintian_brush.upstream_metadata import (
    guess_repo_from_url,
    guess_from_package_json,
    guess_from_debian_watch,
    guess_from_r_description,
    )


class GuessFromDebianWatchTests(TestCaseWithTransport):

    def test_empty(self):
        self.build_tree_contents([('watch', """\
# Blah
""")])
        self.assertEqual(
            [], list(guess_from_debian_watch('watch', False)))

    def test_simple(self):
        self.build_tree_contents([('watch', """\
version=4
https://github.com/jelmer/dulwich/tags/dulwich-(.*).tar.gz
""")])
        self.assertEqual(
            [('Repository', 'https://github.com/jelmer/dulwich', 'possible')],
            list(guess_from_debian_watch('watch', False)))


class GuessFromPackageJsonTests(TestCaseWithTransport):

    def test_simple(self):
        self.build_tree_contents([('package.json', """\
{
  "name": "autosize",
  "version": "4.0.2",
  "author": {
    "name": "Jack Moore",
    "url": "http://www.jacklmoore.com",
    "email": "hello@jacklmoore.com"
  },
  "main": "dist/autosize.js",
  "license": "MIT",
  "homepage": "http://www.jacklmoore.com/autosize",
  "demo": "http://www.jacklmoore.com/autosize",
  "repository": {
    "type": "git",
    "url": "http://github.com/jackmoore/autosize.git"
  }
}
""")])
        self.assertEqual(
            [('Name', 'autosize', 'certain'),
             ('Homepage', 'http://www.jacklmoore.com/autosize', 'certain'),
             ('Repository', 'http://github.com/jackmoore/autosize.git',
              'certain')],
            list(guess_from_package_json('package.json', False)))

    def test_dummy(self):
        self.build_tree_contents([('package.json', """\
{
  "name": "mozillaeslintsetup",
  "description": "This package file is for setup of ESLint.",
  "repository": {},
  "license": "MPL-2.0",
  "dependencies": {
    "eslint": "4.18.1",
    "eslint-plugin-html": "4.0.2",
    "eslint-plugin-mozilla": "file:tools/lint/eslint/eslint-plugin-mozilla",
    "eslint-plugin-no-unsanitized": "2.0.2",
    "eslint-plugin-react": "7.1.0",
    "eslint-plugin-spidermonkey-js":
        "file:tools/lint/eslint/eslint-plugin-spidermonkey-js"
  },
  "devDependencies": {}
}
""")])
        self.assertEqual(
            [('Name', 'mozillaeslintsetup', 'certain')],
            list(guess_from_package_json('package.json', False)))


class GuessFromRDescriptionTests(TestCaseWithTransport):

    def test_read(self):
        self.build_tree_contents([('DESCRIPTION', """\
Package: crul
Title: HTTP Client
Description: A simple HTTP client, with tools for making HTTP requests,
    and mocking HTTP requests. The package is built on R6, and takes
    inspiration from Ruby's 'faraday' gem (<https://rubygems.org/gems/faraday>)
    The package name is a play on curl, the widely used command line tool
    for HTTP, and this package is built on top of the R package 'curl', an
    interface to 'libcurl' (<https://curl.haxx.se/libcurl>).
Version: 0.8.4
License: MIT + file LICENSE
Authors@R: c(
    person("Scott", "Chamberlain", role = c("aut", "cre"),
    email = "myrmecocystus@gmail.com",
    comment = c(ORCID = "0000-0003-1444-9135"))
    )
URL: https://github.com/ropensci/crul (devel)
        https://ropenscilabs.github.io/http-testing-book/ (user manual)
        https://www.example.com/crul (homepage)
BugReports: https://github.com/ropensci/crul/issues
Encoding: UTF-8
Language: en-US
Imports: curl (>= 3.3), R6 (>= 2.2.0), urltools (>= 1.6.0), httpcode
        (>= 0.2.0), jsonlite, mime
Suggests: testthat, fauxpas (>= 0.1.0), webmockr (>= 0.1.0), knitr
VignetteBuilder: knitr
RoxygenNote: 6.1.1
X-schema.org-applicationCategory: Web
X-schema.org-keywords: http, https, API, web-services, curl, download,
        libcurl, async, mocking, caching
X-schema.org-isPartOf: https://ropensci.org
NeedsCompilation: no
Packaged: 2019-08-02 19:58:21 UTC; sckott
Author: Scott Chamberlain [aut, cre] (<https://orcid.org/0000-0003-1444-9135>)
Maintainer: Scott Chamberlain <myrmecocystus@gmail.com>
Repository: CRAN
Date/Publication: 2019-08-02 20:30:02 UTC
""")])
        ret = guess_from_r_description('DESCRIPTION', True)
        self.assertEqual(list(ret), [
            ('Name', 'crul', 'certain'),
            ('Archive', 'CRAN', 'certain'),
            ('Bug-Database', 'https://github.com/ropensci/crul/issues',
                'certain'),
            ('Repository', 'https://github.com/ropensci/crul', 'certain'),
            ('Homepage', 'https://www.example.com/crul', 'certain')])


class GuessRepoFromUrlTests(TestCase):

    def test_github(self):
        self.assertEqual(
            'https://github.com/jelmer/blah',
            guess_repo_from_url('https://github.com/jelmer/blah'))
        self.assertEqual(
            'https://github.com/jelmer/blah',
            guess_repo_from_url('https://github.com/jelmer/blah/blob/README'))
        self.assertIs(
            None,
            guess_repo_from_url('https://github.com/jelmer'))

    def test_none(self):
        self.assertIs(None, guess_repo_from_url('https://www.jelmer.uk/'))

    def test_known(self):
        self.assertEqual(
            'http://code.launchpad.net/blah',
            guess_repo_from_url('http://code.launchpad.net/blah'))

    def test_launchpad(self):
        self.assertEqual(
            'https://code.launchpad.net/bzr',
            guess_repo_from_url('http://launchpad.net/bzr/+download'))
