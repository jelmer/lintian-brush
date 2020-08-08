#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij <jelmer@debian.org>
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

"""Functions for working with upstream metadata."""

import json
import os
import re
import socket
import urllib.error
from typing import Optional
from urllib.parse import quote, urlparse, urlunparse, urljoin, parse_qs
from warnings import warn

from debian.deb822 import Deb822

from debmutate.vcs import (
    split_vcs_url,
    unsplit_vcs_url,
    )

from lintian_brush import (
    USER_AGENT,
    DEFAULT_URLLIB_TIMEOUT,
    SUPPORTED_CERTAINTIES,
    certainty_sufficient,
    certainty_to_confidence,
    min_certainty,
    )
from lintian_brush.vcs import (
    browse_url_from_repo_url,
    plausible_url as plausible_vcs_url,
    sanitize_url as sanitize_vcs_url,
    is_gitlab_site,
    )
from urllib.request import urlopen, Request

# Pecl is quite slow, so up the timeout a bit.
PECL_URLLIB_TIMEOUT = 15
ADDON_ONLY_FIELDS = ['Archive']
KNOWN_HOSTING_SITES = [
    'code.launchpad.net', 'github.com', 'launchpad.net', 'git.openstack.org']


class UpstreamDatum(object):
    """A single piece of upstream metadata."""

    __slots__ = ['field', 'value', 'certainty', 'origin']

    def __init__(self, field, value, certainty=None, origin=None):
        self.field = field
        if value is None:
            raise ValueError(field)
        self.value = value
        if certainty not in SUPPORTED_CERTAINTIES:
            raise ValueError(certainty)
        self.certainty = certainty
        self.origin = origin

    def __eq__(self, other):
        return isinstance(other, type(self)) and \
                self.field == other.field and \
                self.value == other.value and \
                self.certainty == other.certainty and \
                self.origin == other.origin

    def __str__(self):
        return "%s: %s" % (self.field, self.value)

    def __repr__(self):
        return "%s(%r, %r, %r, %r)" % (
            type(self).__name__, self.field, self.value, self.certainty,
            self.origin)


# See https://wiki.debian.org/UpstreamMetadata
# Supported fields:
# - Homepage
# - Name
# - Contact
# - Repository
# - Repository-Browse
# - Bug-Database
# - Bug-Submit
# - Screenshots
# - Archive
# - X-SourceForge-Project
# - X-Wiki
# - X-Summary
# - X-Description
# - X-License
# - X-Copyright

# Supported, but unused.
# - FAQ
# - Donation
# - Documentation
# - Registration
# - Security-Contact
# - Webservice


def _load_json_url(http_url: str, timeout: int = DEFAULT_URLLIB_TIMEOUT):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    http_contents = urlopen(
        Request(http_url, headers=headers),
        timeout=timeout).read()
    return json.loads(http_contents)


class NoSuchSourceForgeProject(Exception):

    def __init__(self, project):
        self.project = project


def get_sf_metadata(project):
    try:
        return _load_json_url(
            'https://sourceforge.net/rest/p/%s' % project)
    except urllib.error.HTTPError as e:
        if e.status != 404:
            raise
        raise NoSuchSourceForgeProject(project)


def guess_repo_from_url(url, net_access=False):
    parsed_url = urlparse(url)
    path_elements = parsed_url.path.strip('/').split('/')
    if parsed_url.netloc == 'github.com':
        if len(path_elements) < 2:
            return None
        return ('https://github.com' +
                '/'.join(parsed_url.path.split('/')[:3]))
    if parsed_url.netloc == 'launchpad.net':
        return 'https://code.launchpad.net/%s' % (
            parsed_url.path.strip('/').split('/')[0])
    if parsed_url.netloc == 'git.savannah.gnu.org':
        if len(path_elements) != 2 or path_elements[0] != 'git':
            return None
        return url
    if parsed_url.netloc in ('freedesktop.org', 'www.freedesktop.org'):
        if len(path_elements) >= 2 and path_elements[0] == 'software':
            return 'https://github.com/freedesktop/%s' % path_elements[1]
        if len(path_elements) >= 3 and path_elements[:2] == [
                'wiki', 'Software']:
            return 'https://github.com/freedesktop/%s.git' % path_elements[2]
    if parsed_url.netloc == 'download.gnome.org':
        if len(path_elements) >= 2 and path_elements[0] == 'sources':
            return 'https://gitlab.gnome.org/GNOME/%s.git' % path_elements[1]
    if parsed_url.netloc == 'download.kde.org':
        if len(path_elements) >= 2 and path_elements[0] in (
                'stable', 'unstable'):
            return 'https://anongit.kde.org/%s.git' % path_elements[1]
    if parsed_url.netloc == 'ftp.gnome.org':
        if (len(path_elements) >= 4 and [
              e.lower() for e in path_elements[:3]] == [
                  'pub', 'gnome', 'sources']):
            return 'https://gitlab.gnome.org/GNOME/%s.git' % path_elements[3]
    if parsed_url.netloc == 'sourceforge.net':
        if (len(path_elements) >= 4 and path_elements[0] == 'p'
                and path_elements[3] == 'ci'):
            return 'https://sourceforge.net/p/%s/%s' % (
                path_elements[1], path_elements[2])
    if parsed_url.netloc == 'www.apache.org':
        if len(path_elements) > 2 and path_elements[0] == 'dist':
            return 'https://svn.apache.org/repos/asf/%s/%s' % (
                path_elements[1], path_elements[2])
    if parsed_url.netloc == 'bitbucket.org':
        if len(path_elements) >= 2:
            return 'https://bitbucket.org/%s/%s' % (
                path_elements[0], path_elements[1])
    if parsed_url.netloc == 'ftp.gnu.org':
        if len(path_elements) >= 2 and path_elements[0] == 'gnu':
            return 'https://git.savannah.gnu.org/git/%s.git' % (
                path_elements[1])
        return None
    if parsed_url.netloc == 'download.savannah.gnu.org':
        if len(path_elements) >= 2 and path_elements[0] == 'releases':
            return 'https://git.savannah.gnu.org/git/%s.git' % (
                path_elements[1])
        return None
    if is_gitlab_site(parsed_url.netloc, net_access):
        if parsed_url.path.strip('/').count('/') < 1:
            return None
        parts = parsed_url.path.split('/')
        if 'tags' in parts:
            parts = parts[:parts.index('tags')]
        if parts[-1] == '-':
            parts.pop(-1)
        return urlunparse(
            parsed_url._replace(path='/'.join(parts), query=''))
    if parsed_url.hostname == 'git.php.net':
        if parsed_url.path.startswith('/repository/'):
            return url
        if not parsed_url.path.strip('/'):
            qs = parse_qs(parsed_url.query)
            if 'p' in qs:
                return urlunparse(parsed_url._replace(
                    path='/repository/' + qs['p'][0], query=''))
    if parsed_url.netloc in KNOWN_HOSTING_SITES:
        return url
    # Maybe it's already pointing at a VCS repo?
    if parsed_url.netloc.startswith('svn.'):
        # 'svn' subdomains are often used for hosting SVN repositories.
        return url
    if net_access:
        if verify_repository_url(url):
            return url
        return None
    return None


def known_bad_guess(datum):
    if datum.field in ('Bug-Submit', 'Bug-Database'):
        parsed_url = urlparse(datum.value)
        if parsed_url.hostname == 'bugzilla.gnome.org':
            return True
        if parsed_url.hostname == 'bugs.freedesktop.org':
            return True
    if datum.field == 'Repository':
        parsed_url = urlparse(datum.value)
        if parsed_url.hostname == 'anongit.kde.org':
            return True
    if datum.field == 'Repository-Browse':
        parsed_url = urlparse(datum.value)
        if parsed_url.hostname == 'cgit.kde.org':
            return True
    if datum.value.lower() == 'unknown':
        return True
    return False


def filter_bad_guesses(guessed_items):
    return filter(lambda x: not known_bad_guess(x), guessed_items)


def update_from_guesses(upstream_metadata, guessed_items):
    changed = False
    for datum in guessed_items:
        current_datum = upstream_metadata.get(datum.field)
        if not current_datum or (
                certainty_to_confidence(datum.certainty) <
                certainty_to_confidence(current_datum.certainty)):
            upstream_metadata[datum.field] = datum
            changed = True
    return changed


def read_python_pkg_info(path):
    """Get the metadata from a python setup.py file."""
    from email.parser import Parser
    from email.message import Message
    try:
        with open(os.path.join(path, 'PKG-INFO'), 'r') as f:
            return Parser().parse(f)
    except FileNotFoundError:
        return Message()


def guess_from_debian_rules(path, trust_package):
    from ..rules import Makefile
    mf = Makefile.from_path(path)
    try:
        upstream_git = mf.get_variable(b'UPSTREAM_GIT')
    except KeyError:
        pass
    else:
        yield UpstreamDatum(
            "Repository", sanitize_vcs_url(upstream_git.decode()), "certain")
    try:
        upstream_url = mf.get_variable(b'DEB_UPSTREAM_URL')
    except KeyError:
        pass
    else:
        yield UpstreamDatum("X-Download", upstream_url.decode(), "certain")


def guess_from_debian_watch(path, trust_package):
    from debmutate.watch import (
        parse_watch_file,
        MissingVersion,
        )

    def get_package_name():
        with open(os.path.join(os.path.dirname(path), 'control'), 'r') as f:
            return Deb822(f)['Source']
    with open(path, 'r') as f:
        try:
            wf = parse_watch_file(f)
        except MissingVersion:
            return
        if not wf:
            return
        for w in wf:
            url = w.format_url(package=get_package_name)
            if 'mode=git' in w.options:
                yield UpstreamDatum(
                    "Repository", sanitize_vcs_url(url), "confident")
                continue
            if url.startswith('https://') or url.startswith('http://'):
                repo = guess_repo_from_url(url)
                if repo:
                    yield UpstreamDatum(
                        "Repository", sanitize_vcs_url(repo), "likely")
                    continue
            m = re.match('https?://sf.net/([^/]+)', url)
            if m:
                yield UpstreamDatum("Archive", "SourceForge", "certain")
                yield UpstreamDatum(
                    "X-SourceForge-Project", m.group(1), "certain")
                continue


def guess_from_debian_control(path, trust_package):
    with open(path, 'r') as f:
        control = Deb822(f)
    if 'Homepage' in control:
        yield UpstreamDatum('Homepage', control['Homepage'], 'certain')
    if 'XS-Go-Import-Path' in control:
        yield (
            UpstreamDatum(
                'Repository',
                sanitize_vcs_url('https://' + control['XS-Go-Import-Path']),
                'likely'))


def guess_from_python_metadata(pkg_info):
    if 'Name' in pkg_info:
        yield UpstreamDatum('Name', pkg_info['name'], 'certain')
    if 'Version' in pkg_info:
        yield UpstreamDatum('X-Version', pkg_info['Version'], 'certain')
    if 'Home-Page' in pkg_info:
        repo = guess_repo_from_url(pkg_info['Home-Page'])
        if repo:
            yield UpstreamDatum(
                'Repository', sanitize_vcs_url(repo), 'likely')
    for value in pkg_info.get_all('Project-URL', []):
        url_type, url = value.split(', ')
        if url_type in ('GitHub', 'Repository', 'Source Code'):
            yield UpstreamDatum(
                'Repository', sanitize_vcs_url(url), 'certain')
        if url_type in ('Bug Tracker', ):
            yield UpstreamDatum(
                'Bug-Database', url, 'certain')
    if 'Summary' in pkg_info:
        yield UpstreamDatum('X-Summary', pkg_info['Summary'], 'certain')
    payload = pkg_info.get_payload()
    if payload.strip() and pkg_info.get_content_type() in (None, 'text/plain'):
        yield UpstreamDatum(
            'X-Description', pkg_info.get_payload(), 'possible')


def guess_from_pkg_info(path, trust_package):
    """Get the metadata from a python setup.py file."""
    from email.parser import Parser
    try:
        with open(path, 'r') as f:
            pkg_info = Parser().parse(f)
    except FileNotFoundError:
        return
    yield from guess_from_python_metadata(pkg_info)


def guess_from_setup_py(path, trust_package):
    if not trust_package:
        return
    from distutils.core import run_setup
    result = run_setup(os.path.abspath(path), stop_after="init")
    if result.get_name() not in (None, '', 'UNKNOWN'):
        yield UpstreamDatum('Name', result.get_name(), 'certain')
    if result.get_version() not in (None, '', 'UNKNOWN'):
        yield UpstreamDatum('X-Version', result.get_version(), 'certain')
    if result.get_url() not in (None, '', 'UNKNOWN'):
        repo = guess_repo_from_url(result.get_url())
        if repo:
            yield UpstreamDatum(
                'Repository', sanitize_vcs_url(repo), 'likely')
    if result.get_download_url() not in (None, '', 'UNKNOWN'):
        yield UpstreamDatum(
            'X-Download', result.get_download_url(), 'likely')
    if result.get_contact() not in (None, '', 'UNKNOWN'):
        contact = result.get_contact()
        if result.get_contact_email() not in (None, '', 'UNKNOWN'):
            contact += " <%s>" % result.get_contact_email()
        yield UpstreamDatum('Contact', contact, 'likely')
    if result.get_description() not in (None, '', 'UNKNOWN'):
        yield UpstreamDatum('X-Summary', result.get_description(), 'certain')
    if (result.metadata.long_description_content_type in (None, 'text/plain')
            and result.metadata.long_description not in (None, '', 'UNKNOWN')):
        yield UpstreamDatum(
            'X-Description', result.metadata.long_description, 'possible')
    for url_type, url in result.metadata.project_urls.items():
        if url_type in ('GitHub', 'Repository', 'Source Code'):
            yield UpstreamDatum(
                'Repository', sanitize_vcs_url(url), 'certain')
        if url_type in ('Bug Tracker', ):
            yield UpstreamDatum(
                'Bug-Database', url, 'certain')


def guess_from_package_json(path, trust_package):
    import json
    with open(path, 'r') as f:
        package = json.load(f)
    if 'name' in package:
        yield UpstreamDatum('Name', package['name'], 'certain')
    if 'homepage' in package:
        yield UpstreamDatum('Homepage', package['homepage'], 'certain')
    if 'repository' in package:
        if isinstance(package['repository'], dict):
            repo_url = package['repository'].get('url')
        elif isinstance(package['repository'], str):
            repo_url = package['repository']
        else:
            repo_url = None
        if repo_url:
            parsed_url = urlparse(repo_url)
            if parsed_url.scheme and parsed_url.netloc:
                yield UpstreamDatum(
                    'Repository', sanitize_vcs_url(repo_url), 'certain')
            else:
                # Some people seem to default to github. :(
                repo_url = 'https://github.com/' + parsed_url.path
                yield UpstreamDatum(
                    'Repository', sanitize_vcs_url(repo_url), 'likely')
    if 'bugs' in package:
        if isinstance(package['bugs'], dict):
            url = package['bugs'].get('url')
        else:
            url = package['bugs']
        if url:
            yield UpstreamDatum('Bug-Database', url, 'certain')


def xmlparse_simplify_namespaces(path, namespaces):
    import xml.etree.ElementTree as ET
    namespaces = ['{%s}' % ns for ns in namespaces]
    tree = ET.iterparse(path)
    for _, el in tree:
        for namespace in namespaces:
            el.tag = el.tag.replace(namespace, '')
    return tree.root


def guess_from_package_xml(path, trust_package):
    import xml.etree.ElementTree as ET
    try:
        root = xmlparse_simplify_namespaces(path, [
            'http://pear.php.net/dtd/package-2.0',
            'http://pear.php.net/dtd/package-2.1'])
    except ET.ParseError as e:
        warn('Unable to parse package.xml: %s' % e)
        return
    assert root.tag == 'package', 'root tag is %r' % root.tag
    name_tag = root.find('name')
    if name_tag is not None:
        yield UpstreamDatum('Name', name_tag.text, 'certain')
    for url_tag in root.findall('url'):
        if url_tag.get('type') == 'repository':
            yield UpstreamDatum(
                'Repository', sanitize_vcs_url(url_tag.text), 'certain')
        if url_tag.get('type') == 'bugtracker':
            yield UpstreamDatum('Bug-Database', url_tag.text, 'certain')


def guess_from_dist_ini(path, trust_package):
    from configparser import (
        RawConfigParser,
        NoSectionError,
        ParsingError,
        NoOptionError,
        )
    parser = RawConfigParser(strict=False)
    with open(path, 'r') as f:
        try:
            parser.read_string('[START]\n' + f.read())
        except ParsingError as e:
            warn('Unable to parse dist.ini: %r' % e)
    try:
        yield UpstreamDatum('Name', parser['START']['name'], 'certain')
    except (NoSectionError, NoOptionError, KeyError):
        pass
    try:
        yield UpstreamDatum(
            'Bug-Database', parser['MetaResources']['bugtracker.web'],
            'certain')
    except (NoSectionError, NoOptionError, KeyError):
        pass
    try:
        yield UpstreamDatum(
            'Repository', parser['MetaResources']['repository.url'], 'certain')
    except (NoSectionError, NoOptionError, KeyError):
        pass


def guess_from_debian_copyright(path, trust_package):
    from debian.copyright import (
        Copyright,
        NotMachineReadableError,
        MachineReadableFormatError,
        )
    with open(path, 'r') as f:
        try:
            copyright = Copyright(f, strict=False)
        except NotMachineReadableError:
            header = None
        except MachineReadableFormatError as e:
            warn('Error parsing copyright file: %s' % e)
            header = None
        except ValueError as e:
            # This can happen with an error message of
            # ValueError: value must not have blank lines
            warn('Error parsing copyright file: %s' % e)
            header = None
        else:
            header = copyright.header
    if header:
        if header.upstream_name:
            yield UpstreamDatum("Name", header.upstream_name, 'certain')
        if header.upstream_contact:
            yield UpstreamDatum(
                "Contact", ','.join(header.upstream_contact), 'certain')
        if header.source:
            if ' ' in header.source:
                from_urls = [u for u in re.split('[ ,\n]', header.source) if u]
            else:
                from_urls = [header.source]
            for from_url in from_urls:
                repo_url = guess_repo_from_url(from_url)
                if repo_url:
                    yield UpstreamDatum(
                        'Repository', sanitize_vcs_url(repo_url), 'likely')
                if (from_url.startswith('https://pecl.php.net/package/') or
                        from_url.startswith('http://pecl.php.net/package/')):
                    yield UpstreamDatum('X-Pecl-URL', from_url, 'certain')
        if "X-Upstream-Bugs" in header:
            yield UpstreamDatum(
                "Bug-Database", header["X-Upstream-Bugs"], 'certain')
        if "X-Source-Downloaded-From" in header:
            url = guess_repo_from_url(header["X-Source-Downloaded-From"])
            if url is not None:
                yield UpstreamDatum("Repository", url, 'certain')


def guess_from_readme(path, trust_package):
    import shlex
    urls = []
    try:
        with open(path, 'rb') as f:
            lines = list(f.readlines())
            for i, line in enumerate(lines):
                line = line.strip()
                if line.strip().lstrip(b'$').strip().startswith(b'git clone'):
                    line = line.strip().lstrip(b'$').strip()
                    while line.endswith(b'\\'):
                        line += lines[i+1]
                        line = line.strip()
                        i += 1
                    argv = shlex.split(line.decode('utf-8', 'replace'))
                    args = [arg for arg in argv[2:]
                            if not arg.startswith('-') and arg.strip()]
                    try:
                        url = args[-2]
                    except IndexError:
                        url = args[0]
                    if plausible_vcs_url(url):
                        urls.append(sanitize_vcs_url(url))
                project_re = b'([^/]+)/([^/?.()"#>\\s]*[^-/?.()"#>\\s])'
                for m in re.finditer(
                        b'https://travis-ci.org/' + project_re, line):
                    yield UpstreamDatum(
                        'Repository', 'https://github.com/%s/%s' % (
                            m.group(1).decode(), m.group(2).decode().rstrip()),
                        'possible')
                for m in re.finditer(
                        b'https://coveralls.io/r/' + project_re, line):
                    yield UpstreamDatum(
                        'Repository', 'https://github.com/%s/%s' % (
                            m.group(1).decode(), m.group(2).decode().rstrip()),
                        'possible')
                for m in re.finditer(
                        b'https://github.com/([^/]+)/([^/]+)/issues', line):
                    yield UpstreamDatum(
                        'Bug-Database',
                        m.group(0).decode().rstrip(), 'possible')
                for m in re.finditer(
                        b'https://github.com/' + project_re + b'(.git)?',
                        line):
                    yield UpstreamDatum(
                        'Repository',
                        m.group(0).rstrip(b'.').decode().rstrip(),
                        'possible')
                m = re.fullmatch(
                    b'https://github.com/' + project_re, line)
                if m:
                    yield UpstreamDatum(
                        'Repository',
                        line.strip().rstrip(b'.').decode(), 'possible')
                m = re.fullmatch(b'git://([^ ]+)', line)
                if m:
                    yield UpstreamDatum(
                        'Repository',
                        line.strip().rstrip(b'.').decode(), 'possible')
                for m in re.finditer(
                        b'https://([^/]+)/([^\\s()"#]+)', line):
                    if is_gitlab_site(m.group(1).decode()):
                        yield UpstreamDatum(
                            'Repository',
                            m.group(0).rstrip(b'.').decode().rstrip(),
                            'possible')
    except IsADirectoryError:
        pass

    def prefer_public(url):
        parsed_url = urlparse(url)
        if 'ssh' in parsed_url.scheme:
            return 1
        return 0
    urls.sort(key=prefer_public)
    if urls:
        yield UpstreamDatum('Repository', urls[0], 'possible')


def guess_from_debian_patch(path, trust_package):
    with open(path, 'rb') as f:
        for line in f:
            if line.startswith(b'Forwarded: '):
                forwarded = line.split(b':', 1)[1].strip()
                bug_db = bug_database_from_issue_url(forwarded.decode('utf-8'))
                if bug_db:
                    yield UpstreamDatum('Bug-Database', bug_db, 'possible')
                repo_url = repo_url_from_merge_request_url(
                    forwarded.decode('utf-8'))
                if repo_url:
                    yield UpstreamDatum('Repository', repo_url, 'possible')


def guess_from_meta_json(path, trust_package):
    import json
    with open(path, 'r') as f:
        data = json.load(f)
        if 'name' in data:
            yield UpstreamDatum('Name', data['name'], 'certain')
        if 'resources' in data:
            resources = data['resources']
            if 'bugtracker' in resources and 'web' in resources['bugtracker']:
                yield UpstreamDatum(
                    "Bug-Database", resources["bugtracker"]["web"], 'certain')
                # TODO(jelmer): Support resources["bugtracker"]["mailto"]
            if 'homepage' in resources:
                yield UpstreamDatum(
                    "Homepage", resources["homepage"], 'certain')
            if 'repository' in resources:
                repo = resources['repository']
                if 'url' in repo:
                    yield UpstreamDatum(
                        'Repository', sanitize_vcs_url(repo["url"]), 'certain')
                if 'web' in repo:
                    yield UpstreamDatum(
                        'Repository-Browse', repo['web'], 'certain')


def guess_from_meta_yml(path, trust_package):
    """Guess upstream metadata from a META.yml file.

    See http://module-build.sourceforge.net/META-spec-v1.4.html for the
    specification of the format.
    """
    import ruamel.yaml
    import ruamel.yaml.reader
    with open(path, 'rb') as f:
        try:
            data = ruamel.yaml.load(f, ruamel.yaml.SafeLoader)
        except ruamel.yaml.reader.ReaderError as e:
            warn('Unable to parse META.yml: %s' % e)
            return
        if 'name' in data:
            yield UpstreamDatum('Name', data['name'], 'certain')
        if 'resources' in data:
            resources = data['resources']
            if 'bugtracker' in resources:
                yield UpstreamDatum(
                    'Bug-Database', resources['bugtracker'], 'certain')
            if 'homepage' in resources:
                yield UpstreamDatum(
                    'Homepage', resources['homepage'], 'certain')
            if 'repository' in resources:
                if isinstance(resources['repository'], dict):
                    url = resources['repository'].get('url')
                else:
                    url = resources['repository']
                if url:
                    yield UpstreamDatum(
                        'Repository', sanitize_vcs_url(url), 'certain')


def guess_from_doap(path, trust_package):
    """Guess upstream metadata from a DOAP file.
    """
    from xml.etree import ElementTree
    el = ElementTree.parse(path)
    root = el.getroot()
    DOAP_NAMESPACE = 'http://usefulinc.com/ns/doap#'
    if root.tag == '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF':
        # If things are wrapped in RDF, unpack.
        [root] = list(root)

    if root.tag != ('{%s}Project' % DOAP_NAMESPACE):
        warn('Doap file does not have DOAP project as root')
        return

    def extract_url(el):
        return el.attrib.get(
            '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource')

    for child in root:
        if child.tag == ('{%s}name' % DOAP_NAMESPACE) and child.text:
            yield UpstreamDatum('Name', child.text, 'certain')
        if child.tag == ('{%s}bug-database' % DOAP_NAMESPACE):
            url = extract_url(child)
            if url:
                yield UpstreamDatum('Bug-Database', url, 'certain')
        if child.tag == ('{%s}homepage' % DOAP_NAMESPACE):
            url = extract_url(child)
            if url:
                yield UpstreamDatum('Homepage', url, 'certain')
        if child.tag == ('{%s}download-page' % DOAP_NAMESPACE):
            url = extract_url(child)
            if url:
                yield UpstreamDatum('X-Download', url, 'certain')
        if child.tag == ('{%s}repository' % DOAP_NAMESPACE):
            for repo in child:
                if repo.tag in (
                        '{%s}SVNRepository' % DOAP_NAMESPACE,
                        '{%s}GitRepository' % DOAP_NAMESPACE):
                    repo_location = repo.find(
                        '{http://usefulinc.com/ns/doap#}location')
                    if repo_location is not None:
                        repo_url = extract_url(repo_location)
                    else:
                        repo_url = None
                    if repo_url:
                        yield UpstreamDatum(
                            'Repository', sanitize_vcs_url(repo_url),
                            'certain')
                    web_location = repo.find(
                        '{http://usefulinc.com/ns/doap#}browse')
                    if web_location is not None:
                        web_url = extract_url(web_location)
                    else:
                        web_url = None

                    if web_url:
                        yield UpstreamDatum(
                            'Repository-Browse', web_url, 'certain')


def guess_from_cabal(path, trust_package=False):
    # TODO(jelmer): Perhaps use a standard cabal parser in Python?
    # The current parser is not really correct, but good enough for our needs.
    # https://www.haskell.org/cabal/release/cabal-1.10.1.0/doc/users-guide/
    repo_url = None
    repo_branch = None
    repo_subpath = None
    with open(path, 'r', encoding='utf-8') as f:
        section = None
        for line in f:
            if line.lstrip().startswith('--'):
                # Comment
                continue
            if not line.strip():
                section = None
                continue
            try:
                (field, value) = line.split(':', 1)
            except ValueError:
                if not line.startswith(' '):
                    section = line.strip().lower()
                continue
            # The case of field names is not sigificant
            field = field.lower()
            value = value.strip()
            if not field.startswith(' '):
                if field == 'homepage':
                    yield UpstreamDatum('Homepage', value, 'certain')
                if field == 'bug-reports':
                    yield UpstreamDatum('Bug-Database', value, 'certain')
                if field == 'name':
                    yield UpstreamDatum('Name', value, 'certain')
                if field == 'maintainer':
                    yield UpstreamDatum('Contact', value, 'certain')
                if field == 'copyright':
                    yield UpstreamDatum('X-Copyright', value, 'certain')
                if field == 'license':
                    yield UpstreamDatum('X-License', value, 'certain')
            else:
                field = field.strip()
                if section == 'source-repository head':
                    if field == 'location':
                        repo_url = value
                    if field == 'branch':
                        repo_branch = value
                    if field == 'subdir':
                        repo_subpath = value
    if repo_url:
        yield UpstreamDatum(
            'Repository',
            unsplit_vcs_url(repo_url, repo_branch, repo_subpath),
            'certain')


def is_email_address(value):
    return '@' in value or ' (at) ' in value


def guess_from_configure(path, trust_package=False):
    if os.path.isdir(path):
        return
    with open(path, 'rb') as f:
        for line in f:
            if b'=' not in line:
                continue
            (key, value) = line.strip().split(b'=', 1)
            if b' ' in key:
                continue
            if b'$' in value:
                continue
            value = value.strip()
            if value.startswith(b"'") and value.endswith(b"'"):
                value = value[1:-1]
            if not value:
                continue
            if key == b'PACKAGE_NAME':
                yield UpstreamDatum(
                    'Name', value.decode(), 'certain', './configure')
            elif key == b'PACKAGE_VERSION':
                yield UpstreamDatum(
                    'X-Version', value.decode(), 'certain', './configure')
            elif key == b'PACKAGE_BUGREPORT':
                if value in (b'BUG-REPORT-ADDRESS', ):
                    certainty = 'invalid'
                elif (is_email_address(value.decode()) and
                        not value.endswith(b'gnu.org')):
                    # Downgrade the trustworthiness of this field for most
                    # upstreams if it contains an e-mail address. Most
                    # upstreams seem to just set this to some random address,
                    # and then forget about it.
                    certainty = 'possible'
                else:
                    parsed_url = urlparse(value.decode())
                    if parsed_url.path.strip('/'):
                        certainty = 'certain'
                    else:
                        # It seems unlikely that the bug submit URL lives at
                        # the root.
                        certainty = 'possible'
                if certainty != 'invalid':
                    yield UpstreamDatum(
                        'Bug-Submit', value.decode(), certainty, './configure')
            elif key == b'PACKAGE_URL':
                yield UpstreamDatum(
                    'Homepage', value.decode(), 'certain', './configure')


def guess_from_r_description(path, trust_package=False):
    with open(path, 'rb') as f:
        description = Deb822(f)
        if 'Package' in description:
            yield UpstreamDatum('Name', description['Package'], 'certain')
        if 'Repository' in description:
            yield UpstreamDatum(
                'Archive', description['Repository'], 'certain')
        if 'BugReports' in description:
            yield UpstreamDatum(
                'Bug-Database', description['BugReports'], 'certain')
        if 'URL' in description:
            entries = [entry.strip()
                       for entry in re.split('[\n,]', description['URL'])]
            urls = []
            for entry in entries:
                m = re.match('([^ ]+) \\((.*)\\)', entry)
                if m:
                    url = m.group(1)
                    label = m.group(2)
                else:
                    url = entry
                    label = None
                urls.append((label, url))
            if len(urls) == 1:
                yield UpstreamDatum('Homepage', urls[0][1], 'possible')
            for label, url in urls:
                if label and label.lower() in ('devel', 'repository'):
                    yield UpstreamDatum('Repository', url, 'certain')
                elif label and label.lower() in ('homepage', ):
                    yield UpstreamDatum('Homepage', url, 'certain')
                else:
                    repo_url = guess_repo_from_url(url)
                    if repo_url:
                        yield UpstreamDatum('Repository', repo_url, 'certain')


def guess_from_environment():
    try:
        yield UpstreamDatum(
            'Repository', os.environ['UPSTREAM_BRANCH_URL'], 'certain')
    except KeyError:
        pass


def guess_from_cargo(path, trust_package):
    try:
        from toml.decoder import load, TomlDecodeError
    except ImportError:
        return
    try:
        with open(path, 'r') as f:
            cargo = load(f)
    except FileNotFoundError:
        return
    except TomlDecodeError as e:
        warn('Error parsing toml file %s: %s' % (path, e))
        return
    try:
        package = cargo['package']
    except KeyError:
        pass
    else:
        if 'name' in package:
            yield UpstreamDatum('Name', package['name'], 'certain')
        if 'description' in package:
            yield UpstreamDatum('X-Summary', package['description'], 'certain')
        if 'homepage' in package:
            yield UpstreamDatum('Homepage', package['homepage'], 'certain')
        if 'license' in package:
            yield UpstreamDatum('X-License', package['license'], 'certain')
        if 'repository' in package:
            yield UpstreamDatum('Repository', package['repository'], 'certain')
        if 'version' in package:
            yield UpstreamDatum('X-Version', package['version'], 'confident')


def guess_from_pom_xml(path, trust_package=False):
    # Documentation: https://maven.apache.org/pom.html

    import xml.etree.ElementTree as ET
    try:
        root = xmlparse_simplify_namespaces(path, [
            'http://maven.apache.org/POM/4.0.0'])
    except ET.ParseError as e:
        warn('Unable to parse package.xml: %s' % e)
        return
    assert root.tag == 'project', 'root tag is %r' % root.tag
    name_tag = root.find('name')
    if name_tag is not None:
        yield UpstreamDatum('Name', name_tag.text, 'certain')
    description_tag = root.find('description')
    if description_tag is not None:
        yield UpstreamDatum('X-Summary', description_tag.text, 'certain')
    version_tag = root.find('version')
    if version_tag is not None and '$' not in version_tag.text:
        yield UpstreamDatum('X-Version', version_tag.text, 'certain')
    licenses_tag = root.find('licenses')
    if licenses_tag is not None:
        licenses = []
        for license_tag in licenses_tag.findall('license'):
            name_tag = license_tag.find('name')
            if name_tag is not None:
                licenses.append(name_tag.text)
    for scm_tag in root.findall('scm'):
        url_tag = scm_tag.find('url')
        if url_tag is not None:
            if (url_tag.text.startswith('scm:') and
                    url_tag.text.count(':') >= 3):
                url = url_tag.text.split(':', 2)[2]
            else:
                url = url_tag.text
            yield UpstreamDatum('Repository-Browse', url, 'certain')
        connection_tag = scm_tag.find('connection')
        if connection_tag is not None:
            connection = connection_tag.text
            try:
                (scm, provider, provider_specific) = connection.split(':', 2)
            except ValueError:
                warn('Invalid format for SCM connection: %s' % connection)
                continue
            if scm != 'scm':
                warn('SCM connection does not start with scm: prefix: %s' %
                     connection)
                continue
            yield UpstreamDatum(
                'Repository', sanitize_vcs_url(provider_specific), 'certain')
    for issue_mgmt_tag in root.findall('issueManagement'):
        url_tag = issue_mgmt_tag.find('url')
        if url_tag is not None:
            yield UpstreamDatum('Bug-Database', url_tag.text, 'certain')
    url_tag = root.find('url')
    if url_tag:
        if not url_tag.text.startswith('scm:'):
            # Yeah, uh, not a URL.
            pass
        else:
            yield UpstreamDatum('Homepage', url_tag.text, 'certain')


def guess_from_git_config(path, trust_package=False):
    from dulwich.config import ConfigFile

    cfg = ConfigFile.from_path(path)
    # If there's a remote named upstream, that's a plausible source..
    try:
        urlb = cfg.get((b'remote', b'upstream'), b'url')
    except KeyError:
        pass
    else:
        url = urlb.decode('utf-8')
        yield UpstreamDatum('Repository', url, 'likely')

    # TODO(jelmer): Try origin?


def _get_guessers(path, trust_package=False):
    CANDIDATES = [
        ('debian/watch', guess_from_debian_watch),
        ('debian/control', guess_from_debian_control),
        ('debian/rules', guess_from_debian_rules),
        ('PKG-INFO', guess_from_pkg_info),
        ('package.json', guess_from_package_json),
        ('package.xml', guess_from_package_xml),
        ('dist.ini', guess_from_dist_ini),
        ('debian/copyright', guess_from_debian_copyright),
        ('META.json', guess_from_meta_json),
        ('META.yml', guess_from_meta_yml),
        ('configure', guess_from_configure),
        ('DESCRIPTION', guess_from_r_description),
        ('Cargo.toml', guess_from_cargo),
        ('pom.xml', guess_from_pom_xml),
        ('.git/config', guess_from_git_config),
        ]

    # Search for something Python-y
    found_pkg_info = os.path.exists(os.path.join(path, 'PKG-INFO'))
    for entry in os.scandir(path):
        if entry.name.endswith('.egg-info'):
            CANDIDATES.append(
                (os.path.join(entry.name, 'PKG-INFO'), guess_from_pkg_info))
            found_pkg_info = True
        if entry.name.endswith('.dist-info'):
            CANDIDATES.append(
                (os.path.join(entry.name, 'METADATA'), guess_from_pkg_info))
            found_pkg_info = True
    if not found_pkg_info and os.path.exists(os.path.join(path, 'setup.py')):
        CANDIDATES.append(('setup.py', guess_from_setup_py))

    doap_filenames = [
        n for n in os.listdir(path)
        if n.endswith('.doap') or
        (n.endswith('.xml') and n.startswith('doap_XML_'))]
    if doap_filenames:
        if len(doap_filenames) == 1:
            CANDIDATES.append((doap_filenames[0], guess_from_doap))
        else:
            warn('More than one doap filename, ignoring all: %r' %
                 doap_filenames)

    cabal_filenames = [n for n in os.listdir(path) if n.endswith('.cabal')]
    if cabal_filenames:
        if len(cabal_filenames) == 1:
            CANDIDATES.append((cabal_filenames[0], guess_from_cabal))
        else:
            warn('More than one cabal filename, ignoring all: %r' %
                 cabal_filenames)

    readme_filenames = [
        n for n in os.listdir(path)
        if any([n.startswith(p)
                for p in ['readme', 'README', 'HACKING', 'CONTRIBUTING']])
        and os.path.splitext(n)[1] not in ('.html', '.pdf', '.xml')]
    CANDIDATES.extend([(n, guess_from_readme) for n in readme_filenames])

    try:
        debian_patches = [
            os.path.join('debian', 'patches', n)
            for n in os.listdir('debian/patches')
            if os.path.isfile(os.path.join('debian/patches', n))]
    except FileNotFoundError:
        pass
    else:
        CANDIDATES.extend(
            [(p, guess_from_debian_patch) for p in debian_patches])

    yield guess_from_environment()

    for relpath, guesser in CANDIDATES:
        abspath = os.path.join(path, relpath)
        if not os.path.exists(abspath):
            continue
        yield guesser(abspath, trust_package=trust_package)


def guess_upstream_metadata_items(path, trust_package=False,
                                  minimum_certainty=None):
    """Guess upstream metadata items, in no particular order.

    Args:
      path: Path to the package
      trust: Whether to trust the package contents and i.e. run
      executables in it
    Yields:
      Tuples with (key, value, certainty)
    """
    guessers = _get_guessers(path, trust_package=trust_package)
    for guesser in guessers:
        for datum in guesser:
            if not certainty_sufficient(datum.certainty, minimum_certainty):
                continue
            yield datum


def guess_upstream_metadata(
        path, trust_package=False, net_access=False,
        consult_external_directory=False, check=False):
    """Guess the upstream metadata dictionary.

    Args:
      path: Path to the package
      trust_package: Whether to trust the package contents and i.e. run
          executables in it
      net_access: Whether to allow net access
      consult_external_directory: Whether to pull in data
        from external (user-maintained) directories.
    """
    upstream_metadata = {}
    update_from_guesses(
        upstream_metadata,
        filter_bad_guesses(
            guess_upstream_metadata_items(
                path, trust_package=trust_package)))

    extend_upstream_metadata(
        upstream_metadata, path, net_access=net_access,
        consult_external_directory=consult_external_directory)

    if check:
        check_upstream_metadata(upstream_metadata)

    fix_upstream_metadata(upstream_metadata)

    return {k: v.value for (k, v) in upstream_metadata.items()}


def _possible_fields_missing(upstream_metadata, fields, field_certainty):
    for field in fields:
        if field not in upstream_metadata:
            return True
        if upstream_metadata[field].certainty != 'certain':
            return True
    else:
        return False


def _sf_git_extract_url(page):
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        warn('Not scanning sourceforge page, since python3-bs4 is missing')
        return None
    bs = BeautifulSoup(page, features='lxml')
    el = bs.find(id='access_url')
    if not el:
        return None
    value = el.get('value')
    if value is None:
        return None
    access_command = value.split(' ')
    if access_command[:2] != ['git', 'clone']:
        return None
    return access_command[2]


def guess_from_sf(sf_project):
    try:
        data = get_sf_metadata(sf_project)
    except socket.timeout:
        warn('timeout contacting launchpad, ignoring: %s' % sf_project)
        return
    if data.get('name'):
        yield 'Name', data['name']
    if data.get('external_homepage'):
        yield 'Homepage', data['external_homepage']
    if data.get('preferred_support_url'):
        if verify_bug_database_url(data['preferred_support_url']):
            yield 'Bug-Database', data['preferred_support_url']
    # In theory there are screenshots linked from the sourceforge project that
    # we can use, but if there are multiple "subprojects" then it will be
    # unclear which one they belong to.
    # TODO(jelmer): What about cvs and bzr?
    VCS_NAMES = ['hg', 'git', 'svn']
    vcs_tools = [
        (tool['name'], tool['url'])
        for tool in data.get('tools', []) if tool['name'] in VCS_NAMES]
    if len(vcs_tools) == 1:
        (kind, url) = vcs_tools[0]
        if kind == 'git':
            url = urljoin('https://sourceforge.net/', url)
            headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html'}
            http_contents = urlopen(
                Request(url, headers=headers),
                timeout=DEFAULT_URLLIB_TIMEOUT).read()
            url = _sf_git_extract_url(http_contents)
        elif kind == 'svn':
            url = urljoin('https://svn.code.sf.net/', url)
        elif kind == 'hg':
            url = urljoin('https://hg.code.sf.net/', url)
        else:
            raise KeyError(kind)
        if url is not None:
            yield 'Repository', url


def extend_from_external_guesser(
        upstream_metadata, guesser_certainty, guesser_fields, guesser):
    if not _possible_fields_missing(
            upstream_metadata, guesser_fields, guesser_certainty):
        return

    update_from_guesses(
        upstream_metadata,
        [UpstreamDatum(key, value, guesser_certainty)
         for (key, value) in guesser])


def extend_from_sf(upstream_metadata, sf_project):
    # The set of fields that sf can possibly provide:
    sf_fields = ['Homepage', 'Name', 'Repository']
    sf_certainty = upstream_metadata['Archive'].certainty

    return extend_from_external_guesser(
        upstream_metadata, sf_certainty, sf_fields,
        guess_from_sf(sf_project))


def extend_from_pecl(upstream_metadata, pecl_url, certainty):
    pecl_fields = ['Homepage', 'Repository', 'Bug-Database']

    return extend_from_external_guesser(
        upstream_metadata, certainty, pecl_fields,
        guess_from_pecl_url(pecl_url))


def extend_from_lp(upstream_metadata, minimum_certainty, package,
                   distribution=None, suite=None):
    # The set of fields that Launchpad can possibly provide:
    lp_fields = ['Homepage', 'Repository', 'Name']
    lp_certainty = 'possible'

    if certainty_sufficient(lp_certainty, minimum_certainty):
        # Don't bother talking to launchpad if we're not
        # speculating.
        return

    extend_from_external_guesser(
        upstream_metadata, lp_certainty, lp_fields, guess_from_launchpad(
             package, distribution=distribution, suite=suite))


def extend_from_aur(upstream_metadata, minimum_certainty, package):
    # The set of fields that AUR can possibly provide:
    aur_fields = ['Homepage', 'Repository']
    aur_certainty = 'possible'

    if certainty_sufficient(aur_certainty, minimum_certainty):
        # Don't bother talking to AUR if we're not speculating.
        return

    extend_from_external_guesser(
        upstream_metadata, aur_certainty, aur_fields, guess_from_aur(package))


def extract_sf_project_name(url):
    m = re.fullmatch('https?://(.*).(sf|sourceforge).net/?', url)
    if m:
        return m.group(1)
    m = re.match('https://sourceforge.net/projects/([^/]+)', url)
    if m:
        return m.group(1)


def repo_url_from_merge_request_url(url):
    parsed_url = urlparse(url)
    if parsed_url.netloc == 'github.com':
        path_elements = parsed_url.path.strip('/').split('/')
        if len(path_elements) > 2 and path_elements[2] == 'issues':
            return urlunparse(
                ('https', 'github.com', '/'.join(path_elements[:3]),
                 None, None, None))
    if is_gitlab_site(parsed_url.netloc):
        path_elements = parsed_url.path.strip('/').split('/')
        if (len(path_elements) > 2 and
                path_elements[-2] == 'merge_requests' and
                path_elements[-1].isdigit()):
            return urlunparse(
                ('https', parsed_url.netloc, '/'.join(path_elements[:-2]),
                 None, None, None))


def bug_database_from_issue_url(url):
    parsed_url = urlparse(url)
    if parsed_url.netloc == 'github.com':
        path_elements = parsed_url.path.strip('/').split('/')
        if len(path_elements) > 2 and path_elements[2] == 'issues':
            return urlunparse(
                ('https', 'github.com', '/'.join(path_elements[:3]),
                 None, None, None))
    if is_gitlab_site(parsed_url.netloc):
        path_elements = parsed_url.path.strip('/').split('/')
        if (len(path_elements) > 2 and
                path_elements[-2] == 'issues' and
                path_elements[-1].isdigit()):
            return urlunparse(
                ('https', parsed_url.netloc, '/'.join(path_elements[:-2]),
                 None, None, None))


def guess_bug_database_url_from_repo_url(url):
    url = split_vcs_url(url)[0]
    parsed_url = urlparse(url)
    if parsed_url.netloc == 'github.com':
        path = '/'.join(parsed_url.path.split('/')[:3])
        if path.endswith('.git'):
            path = path[:-4]
        path = path + '/issues'
        return urlunparse(
            ('https', 'github.com', path,
             None, None, None))
    if is_gitlab_site(parsed_url.hostname):
        path = '/'.join(parsed_url.path.split('/')[:3])
        if path.endswith('.git'):
            path = path[:-4]
        path = path + '/issues'
        return urlunparse(
            ('https', parsed_url.hostname, path,
             None, None, None))
    return None


def bug_database_url_from_bug_submit_url(url):
    parsed_url = urlparse(url)
    path_elements = parsed_url.path.strip('/').split('/')
    if parsed_url.netloc == 'github.com':
        if len(path_elements) not in (3, 4):
            return None
        if path_elements[2] != 'issues':
            return None
        return urlunparse(
            ('https', 'github.com', '/'.join(path_elements[:3]),
             None, None, None))
    if parsed_url.netloc == 'bugs.launchpad.net':
        if len(path_elements) >= 1:
            return urlunparse(
                parsed_url._replace(path='/%s' % path_elements[0]))
    if is_gitlab_site(parsed_url.netloc):
        if len(path_elements) < 2:
            return None
        if path_elements[-2] != 'issues':
            return None
        if path_elements[-1] == 'new':
            path_elements.pop(-1)
        return urlunparse(
            parsed_url._replace(path='/'.join(path_elements)))
    return None


def bug_submit_url_from_bug_database_url(url):
    parsed_url = urlparse(url)
    path_elements = parsed_url.path.strip('/').split('/')
    if parsed_url.netloc == 'github.com':
        if len(path_elements) != 3:
            return None
        if path_elements[2] != 'issues':
            return None
        return urlunparse(
            ('https', 'github.com', parsed_url.path + '/new',
             None, None, None))
    if parsed_url.netloc == 'bugs.launchpad.net':
        if len(path_elements) == 1:
            return urlunparse(
                parsed_url._replace(path=parsed_url.path+'/+filebug'))
    if is_gitlab_site(parsed_url.netloc):
        if len(path_elements) < 2:
            return None
        if path_elements[-1] != 'issues':
            return None
        return urlunparse(
            parsed_url._replace(path=parsed_url.path.rstrip('/')+'/new'))
    return None


def verify_repository_url(url: str, version: Optional[str] = None) -> bool:
    """Verify whether a repository URL is valid."""
    parsed_url = urlparse(url)
    if parsed_url.netloc == 'github.com':
        path_elements = parsed_url.path.strip('/').split('/')
        if len(path_elements) < 2:
            return False
        if path_elements[1].endswith('.git'):
            path_elements[1] = path_elements[1][:-4]
        api_url = 'https://api.github.com/repos/%s/%s' % (
            path_elements[0], path_elements[1])
        try:
            data = _load_json_url(api_url)
        except urllib.error.HTTPError as e:
            if e.status == 404:
                return False
            elif e.status == 403:
                # Probably rate-limited. Let's just hope for the best.
                pass
            else:
                raise
        else:
            if data.get('archived', False):
                return False
            if data['description']:
                if data['description'].startswith('Moved to '):
                    return False
                if 'has moved' in data['description']:
                    return False
                if data['description'].startswith('Mirror of '):
                    return False
            homepage = data.get('homepage')
            if homepage and is_gitlab_site(homepage):
                return False
            # TODO(jelmer): Look at the contents of the repository; if it
            # contains just a single README file with < 10 lines, assume
            # the worst.
            # return data['clone_url']
    return probe_upstream_branch_url(url, version=version)


def verify_bug_database_url(url):
    parsed_url = urlparse(url)
    if parsed_url.netloc == 'github.com':
        path_elements = parsed_url.path.strip('/').split('/')
        if len(path_elements) < 3 or path_elements[2] != 'issues':
            return False
        api_url = 'https://api.github.com/repos/%s/%s' % (
            path_elements[0], path_elements[1])
        try:
            data = _load_json_url(api_url)
        except urllib.error.HTTPError as e:
            if e.status == 404:
                return False
            if e.status == 403:
                # Probably rate limited
                warn('Unable to verify bug database URL %s: %s' % (
                     url, e.reason))
                return None
            raise
        return data['has_issues'] and not data.get('archived', False)
    if is_gitlab_site(parsed_url.netloc):
        path_elements = parsed_url.path.strip('/').split('/')
        if len(path_elements) < 3 or path_elements[-1] != 'issues':
            return False
        api_url = 'https://%s/api/v4/projects/%s/issues' % (
            parsed_url.netloc, quote('/'.join(path_elements[:-1]), safe=''))
        try:
            data = _load_json_url(api_url)
        except urllib.error.HTTPError as e:
            if e.status == 404:
                return False
            raise
        return len(data) > 0
    return None


def verify_bug_submit_url(url):
    parsed_url = urlparse(url)
    if parsed_url.netloc == 'github.com' or is_gitlab_site(parsed_url.netloc):
        path = '/'.join(parsed_url.path.strip('/').split('/')[:-1])
        return verify_bug_database_url(
            urlunparse(parsed_url._replace(path=path)))
    return None


def _extrapolate_repository_from_homepage(upstream_metadata, net_access):
    repo = guess_repo_from_url(
            upstream_metadata['Homepage'].value, net_access=net_access)
    if repo:
        return UpstreamDatum(
            'Repository', repo,
            min_certainty(['likely', upstream_metadata['Homepage'].certainty]))


def _extrapolate_repository_from_download(upstream_metadata, net_access):
    repo = guess_repo_from_url(
            upstream_metadata['X-Download'].value, net_access=net_access)
    if repo:
        return UpstreamDatum(
            'Repository', repo,
            min_certainty(
                ['likely', upstream_metadata['X-Download'].certainty]))


def _extrapolate_repository_from_bug_db(upstream_metadata, net_access):
    repo = guess_repo_from_url(
        upstream_metadata['Bug-Database'].value, net_access=net_access)
    if repo:
        return UpstreamDatum(
            'Repository', repo,
            min_certainty(
                ['likely', upstream_metadata['Bug-Database'].certainty]))


def _extrapolate_name_from_repository(upstream_metadata, net_access):
    repo = guess_repo_from_url(
            upstream_metadata['Repository'].value, net_access=net_access)
    if repo:
        parsed = urlparse(repo)
        name = parsed.path.split('/')[-1]
        if name.endswith('.git'):
            name = name[:-4]
        return UpstreamDatum('Name', name, min_certainty(
                ['likely', upstream_metadata['Repository'].certainty]))


def _extrapolate_repository_browse_from_repository(
        upstream_metadata, net_access):
    browse_url = browse_url_from_repo_url(
            upstream_metadata['Repository'].value)
    if browse_url:
        return UpstreamDatum(
            'Repository-Browse', browse_url,
            upstream_metadata['Repository'].certainty)


def _extrapolate_repository_from_repository_browse(
        upstream_metadata, net_access):
    repo = guess_repo_from_url(
        upstream_metadata['Repository-Browse'].value,
        net_access=net_access)
    if repo:
        return UpstreamDatum(
            'Repository', repo,
            upstream_metadata['Repository-Browse'].certainty)


def _extrapolate_bug_database_from_repository(
        upstream_metadata, net_access):
    bug_db_url = guess_bug_database_url_from_repo_url(
        upstream_metadata['Repository'].value)
    if bug_db_url:
        return UpstreamDatum(
            'Bug-Database', bug_db_url,
            min_certainty(
                ['likely', upstream_metadata['Repository'].certainty]))


def _extrapolate_bug_submit_from_bug_db(
        upstream_metadata, net_access):
    bug_submit_url = bug_submit_url_from_bug_database_url(
        upstream_metadata['Bug-Database'].value)
    if bug_submit_url:
        return UpstreamDatum(
            'Bug-Submit', bug_submit_url,
            upstream_metadata['Bug-Database'].certainty)


def _extrapolate_bug_db_from_bug_submit(
        upstream_metadata, net_access):
    bug_db_url = bug_database_url_from_bug_submit_url(
        upstream_metadata['Bug-Submit'].value)
    if bug_db_url:
        return UpstreamDatum(
            'Bug-Database', bug_db_url,
            upstream_metadata['Bug-Submit'].certainty)


def _copy_bug_db_field(upstream_metadata, net_access):
    ret = UpstreamDatum(
        'Bug-Database',
        upstream_metadata['Bugs-Database'].value,
        upstream_metadata['Bugs-Database'].certainty,
        upstream_metadata['Bugs-Database'].origin)
    del upstream_metadata['Bugs-Database']
    return ret


EXTRAPOLATE_FNS = [
    ('Homepage', 'Repository', _extrapolate_repository_from_homepage),
    ('Bugs-Database', 'Bug-Database', _copy_bug_db_field),
    ('Bug-Database', 'Repository', _extrapolate_repository_from_bug_db),
    ('Repository', 'Repository-Browse',
     _extrapolate_repository_browse_from_repository),
    ('Repository-Browse', 'Repository',
     _extrapolate_repository_from_repository_browse),
    ('Repository', 'Bug-Database',
     _extrapolate_bug_database_from_repository),
    ('Bug-Database', 'Bug-Submit', _extrapolate_bug_submit_from_bug_db),
    ('Bug-Submit', 'Bug-Database', _extrapolate_bug_db_from_bug_submit),
    ('X-Download', 'Repository', _extrapolate_repository_from_download),
    ('Repository', 'Name', _extrapolate_name_from_repository),
]


def extend_upstream_metadata(upstream_metadata, path, minimum_certainty=None,
                             net_access=False,
                             consult_external_directory=False):
    """Extend a set of upstream metadata.
    """
    if 'Homepage' in upstream_metadata:
        project = extract_sf_project_name(upstream_metadata['Homepage'].value)
        if project:
            upstream_metadata['Archive'] = UpstreamDatum(
                'Archive', 'SourceForge', 'likely')
            upstream_metadata['X-SourceForge-Project'] = UpstreamDatum(
                'X-SourceForge-Project', project, 'likely')

    archive = upstream_metadata.get('Archive')
    if (archive and archive.value == 'SourceForge' and
            'X-SourceForge-Project' in upstream_metadata and
            net_access):
        sf_project = upstream_metadata['X-SourceForge-Project'].value
        try:
            extend_from_sf(upstream_metadata, sf_project)
        except NoSuchSourceForgeProject:
            del upstream_metadata['X-SourceForge-Project']
    if net_access and consult_external_directory:
        try:
            with open(os.path.join(path, 'debian/control'), 'r') as f:
                package = Deb822(f)['Source']
        except FileNotFoundError:
            # Huh, okay.
            pass
        else:
            extend_from_lp(upstream_metadata, minimum_certainty, package)
            extend_from_aur(upstream_metadata, minimum_certainty, package)
    pecl_url = upstream_metadata.get('X-Pecl-URL')
    if net_access and pecl_url:
        extend_from_pecl(upstream_metadata, pecl_url.value, pecl_url.certainty)
    changed = True
    while changed:
        changed = False
        for from_field, to_field, fn in EXTRAPOLATE_FNS:
            try:
                from_value = upstream_metadata[from_field]
            except KeyError:
                continue
            old_to_value = upstream_metadata.get(to_field)
            if old_to_value is not None and (
                    certainty_to_confidence(from_value.certainty) >=
                    certainty_to_confidence(old_to_value.certainty)):
                continue
            result = fn(upstream_metadata, net_access)
            if not result:
                continue
            if not certainty_sufficient(result.certainty, minimum_certainty):
                continue
            if old_to_value is None or (
                    certainty_to_confidence(result.certainty) <
                    certainty_to_confidence(old_to_value.certainty)):
                upstream_metadata[to_field] = result
                changed = True


def _version_in_tags(version, tag_names):
    if version in tag_names:
        return True
    if 'v%s' % version in tag_names:
        return True
    if 'release/%s' % version in tag_names:
        return True
    if version.replace('.', '_') in tag_names:
        return True
    for tag_name in tag_names:
        if tag_name.endswith('_' + version):
            return True
        if tag_name.endswith('-' + version):
            return True
        if tag_name.endswith('_%s' % version.replace('.', '_')):
            return True
    return False


def probe_upstream_branch_url(url, version=None):
    parsed = urlparse(url)
    if parsed.scheme in ('git+ssh', 'ssh', 'bzr+ssh'):
        # Let's not probe anything possibly non-public.
        return None
    import breezy.ui
    from breezy.branch import Branch
    old_ui = breezy.ui.ui_factory
    breezy.ui.ui_factory = breezy.ui.SilentUIFactory()
    try:
        b = Branch.open(url)
        b.last_revision()
        if version is not None:
            version = version.split('+git')[0]
            tag_names = b.tags.get_tag_dict().keys()
            if not tag_names:
                # Uhm, hmm
                return True
            if _version_in_tags(version, tag_names):
                return True
            return False
        else:
            return True
    except Exception:
        # TODO(jelmer): Catch more specific exceptions?
        return False
    finally:
        breezy.ui.ui_factory = old_ui


def verify_screenshots(urls):
    headers = {'User-Agent': USER_AGENT}
    for url in urls:
        try:
            response = urlopen(
                Request(url, headers=headers, method='HEAD'),
                timeout=DEFAULT_URLLIB_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.status == 404:
                yield url, False
            else:
                yield url, None
        else:
            assert response is not None
            # TODO(jelmer): Check content-type?
            yield url, True


def check_upstream_metadata(upstream_metadata, version=None):
    """Check upstream metadata.

    This will make network connections, etc.
    """
    repository = upstream_metadata.get('Repository')
    if repository and repository.certainty == 'likely':
        if verify_repository_url(repository.value, version=version):
            repository.certainty = 'certain'
            derived_browse_url = browse_url_from_repo_url(repository.value)
            browse_repo = upstream_metadata.get('Repository-Browse')
            if browse_repo and derived_browse_url == browse_repo.value:
                browse_repo.certainty = repository.certainty
        else:
            # TODO(jelmer): Remove altogether, or downgrade to a lesser
            # certainty?
            pass
    bug_database = upstream_metadata.get('Bug-Database')
    if bug_database and bug_database.certainty == 'likely':
        if verify_bug_database_url(bug_database.value):
            bug_database.certainty = 'certain'
    bug_submit = upstream_metadata.get('Bug-Submit')
    if bug_submit and bug_submit.certainty == 'likely':
        if verify_bug_submit_url(bug_submit.value):
            bug_submit.certainty = 'certain'
    screenshots = upstream_metadata.get('Screenshots')
    if screenshots and screenshots.certainty == 'likely':
        newvalue = []
        screenshots.certainty = 'certain'
        for i, (url, status) in enumerate(verify_screenshots(
                screenshots.value)):
            if status is True:
                newvalue.append(url)
            elif status is False:
                pass
            else:
                screenshots.certainty = 'likely'
        screenshots.value = newvalue


def parse_pkgbuild_variables(f):
    import shlex
    variables = {}
    keep = None
    existing = None
    for line in f:
        if existing:
            line = existing + line
        if line.endswith(b'\\\n'):
            existing = line[:-2]
            continue
        existing = None
        if (line.startswith(b'\t') or line.startswith(b' ') or
                line.startswith(b'#')):
            continue
        if keep:
            keep = (keep[0], keep[1] + line)
            if line.rstrip().endswith(b')'):
                variables[keep[0].decode()] = shlex.split(
                    keep[1].rstrip(b'\n').decode())
                keep = None
            continue
        try:
            (key, value) = line.split(b'=', 1)
        except ValueError:
            continue
        if value.startswith(b'('):
            if value.rstrip().endswith(b')'):
                value = value.rstrip()[1:-1]
            else:
                keep = (key, value[1:])
                continue
        variables[key.decode()] = shlex.split(value.rstrip(b'\n').decode())
    return variables


def guess_from_pecl(package):
    if not package.startswith('php-'):
        return iter([])
    php_package = package[4:]
    url = 'https://pecl.php.net/packages/%s' % php_package.replace('-', '_')
    data = dict(guess_from_pecl_url(url))
    try:
        data['Repository'] = guess_repo_from_url(
                data['Repository-Browse'], net_access=True)
    except KeyError:
        pass
    return data.items()


def guess_from_pecl_url(url):
    headers = {'User-Agent': USER_AGENT}
    try:
        f = urlopen(
            Request(url, headers=headers),
            timeout=PECL_URLLIB_TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.status != 404:
            raise
        return
    except socket.timeout:
        warn('timeout contacting pecl, ignoring: %s' % url)
        return
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        warn('bs4 missing so unable to scan pecl page, ignoring %s' % url)
        return
    bs = BeautifulSoup(f.read(), features='lxml')
    tag = bs.find('a', text='Browse Source')
    if tag is not None:
        yield 'Repository-Browse', tag.attrs['href']
    tag = bs.find('a', text='Package Bugs')
    if tag is not None:
        yield 'Bug-Database', tag.attrs['href']
    label_tag = bs.find('th', text='Homepage')
    if label_tag is not None:
        tag = label_tag.parent.find('a')
        if tag is not None:
            yield 'Homepage', tag.attrs['href']


def guess_from_aur(package: str):
    vcses = ['git', 'bzr', 'hg']
    for vcs in vcses:
        url = (
            'https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=%s-%s' %
            (package, vcs))
        headers = {'User-Agent': USER_AGENT}
        try:
            f = urlopen(
                Request(url, headers=headers),
                timeout=DEFAULT_URLLIB_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.status != 404:
                raise
            continue
        else:
            break
    else:
        return

    variables = parse_pkgbuild_variables(f)
    for key, value in variables.items():
        if key == 'url':
            yield 'Homepage', value[0]
        if key == 'source':
            if not value:
                continue
            value = value[0]
            if "${" in value:
                for k, v in variables.items():
                    value = value.replace('${%s}' % k, ' '.join(v))
                    value = value.replace('$%s' % k, ' '.join(v))
            try:
                unique_name, url = value.split('::', 1)
            except ValueError:
                url = value
            url = url.replace('#branch=', ',branch=')
            if any([url.startswith(vcs+'+') for vcs in vcses]):
                yield 'Repository', sanitize_vcs_url(url)
        if key == '_gitroot':
            yield 'Repository', sanitize_vcs_url(value[0])


def guess_from_launchpad(package, distribution=None, suite=None):
    if distribution is None:
        # Default to Ubuntu; it's got more fields populated.
        distribution = 'ubuntu'
    if suite is None:
        if distribution == 'ubuntu':
            from distro_info import UbuntuDistroInfo, DistroDataOutdated
            ubuntu = UbuntuDistroInfo()
            try:
                suite = ubuntu.devel()
            except DistroDataOutdated as e:
                warn(str(e))
                suite = ubuntu.all[-1]
        elif distribution == 'debian':
            suite = 'sid'
    sourcepackage_url = (
        'https://api.launchpad.net/devel/%(distribution)s/'
        '%(suite)s/+source/%(package)s' % {
            'package': package,
            'suite': suite,
            'distribution': distribution})
    try:
        sourcepackage_data = _load_json_url(sourcepackage_url)
    except urllib.error.HTTPError as e:
        if e.status != 404:
            raise
        return
    except socket.timeout:
        warn('timeout contacting launchpad, ignoring')
        return

    productseries_url = sourcepackage_data.get('productseries_link')
    if not productseries_url:
        return
    productseries_data = _load_json_url(productseries_url)
    project_link = productseries_data['project_link']
    project_data = _load_json_url(project_link)
    if project_data.get('homepage_url'):
        yield 'Homepage', project_data['homepage_url']
    yield 'Name', project_data['display_name']
    if project_data.get('sourceforge_project'):
        yield ('X-SourceForge-Project', project_data['sourceforge_project'])
    if project_data.get('wiki_url'):
        yield ('X-Wiki', project_data['wiki_url'])
    if project_data.get('summary'):
        yield ('X-Summary', project_data['summary'])
    if project_data['vcs'] == 'Bazaar':
        branch_link = productseries_data.get('branch_link')
        if branch_link:
            try:
                code_import_data = _load_json_url(
                    branch_link + '/+code-import')
                if code_import_data['url']:
                    # Sometimes this URL is not set, e.g. for CVS repositories.
                    yield 'Repository', code_import_data['url']
            except urllib.error.HTTPError as e:
                if e.status != 404:
                    raise
                if project_data['official_codehosting']:
                    try:
                        branch_data = _load_json_url(branch_link)
                    except urllib.error.HTTPError as e:
                        if e.status != 404:
                            raise
                        branch_data = None
                    if branch_data:
                        yield 'Archive', 'launchpad'
                        yield 'Repository', branch_data['bzr_identity']
                        yield 'Repository-Browse', branch_data['web_link']
    elif project_data['vcs'] == 'Git':
        repo_link = (
            'https://api.launchpad.net/devel/+git?ws.op=getByPath&path=%s' %
            project_data['name'])
        repo_data = _load_json_url(repo_link)
        if not repo_data:
            return
        code_import_link = repo_data.get('code_import_link')
        if code_import_link:
            code_import_data = _load_json_url(repo_data['code_import_link'])
            if code_import_data['url']:
                # Sometimes this URL is not set, e.g. for CVS repositories.
                yield 'Repository', code_import_data['url']
        else:
            if project_data['official_codehosting']:
                yield 'Archive', 'launchpad'
                yield 'Repository', repo_data['git_https_url']
                yield 'Repository-Browse', repo_data['web_link']
    elif project_data.get('vcs') is not None:
        raise AssertionError('unknown vcs: %r' % project_data['vcs'])


def fix_upstream_metadata(upstream_metadata):
    """Fix existing upstream metadata."""
    if 'Repository' in upstream_metadata:
        repo = upstream_metadata['Repository']
        url = repo.value
        url = sanitize_vcs_url(url)
        repo.value = url


# If we're setting them new, put Name and Contact first
def upstream_metadata_sort_key(x):
    (k, v) = x
    return {
        'Name': '00-Name',
        'Contact': '01-Contact',
        }.get(k, k)


def upstream_version(version):
    """Drop debian-specific modifiers from an upstream version string.
    """
    return version.upstream_version.split("+dfsg")[0]
