#!/usr/bin/python3
# Copyright (C) 2020 Jelmer Vernooij
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

"""Debianize a package."""

__all__ = [
    'NoBuildToolsFound',
    'debianize',
    ]

import contextlib
import logging
import os
import shutil
import sys
from typing import Optional
from urllib.parse import urlparse
import warnings


from debian.changelog import Changelog, Version, get_maintainer, format_date
from debmutate.control import ensure_some_version, ensure_exact_version, ensure_relation, ControlEditor
from debian.deb822 import PkgRelation

from breezy import osutils
from breezy.branch import Branch
from breezy.errors import AlreadyBranchError
from breezy.commit import NullCommitReporter
from breezy.workingtree import WorkingTree

from ognibuild import DetailedFailure, UnidentifiedError
from ognibuild.buildsystem import get_buildsystem, NoBuildToolsFound
from ognibuild.debian.apt import AptManager
from ognibuild.debian.build import DEFAULT_BUILDER
from ognibuild.dist import (  # noqa: F401
    DistNoTarball,
    create_dist as ogni_create_dist,
    )
from ognibuild.session.plain import PlainSession
from ognibuild.session.schroot import SchrootSession
from ognibuild.resolver.apt import AptResolver
from ognibuild.buildlog import InstallFixer

from upstream_ontologist.guess import (
    guess_upstream_info,
    summarize_upstream_metadata,
)
from upstream_ontologist.debian import (
    upstream_name_to_debian_source_name as source_name_from_upstream_name,
    upstream_version_to_debian_upstream_version as debian_upstream_version,
    valid_debian_package_name,
)

from breezy.plugins.debian.upstream.pristinetar import get_pristine_tar_source

from . import (
    available_lintian_fixers,
    version_string,
    check_clean_tree,
    PendingChanges,
    run_lintian_fixers,
    get_committer,
    reset_tree,
)
from .debhelper import (
    maximum_debhelper_compat_version,
    write_rules_template as write_debhelper_rules_template,
)
from .publish import update_offical_vcs, NoVcsLocation, VcsAlreadySpecified
from .standards_version import latest_standards_version


class SourcePackageNameInvalid(Exception):
    """Source package name is invalid."""

    def __init__(self, source):
        self.source = source


class SourceNameUnknown(Exception):
    """Unable to determine source name."""

    def __init__(self, upstream_name):
        self.upstream_name = upstream_name


class DistCreationFailed(Exception):
    """Dist tarball creation failed."""

    def __init__(self, msg, inner=None):
        self.msg = msg
        self.inner = inner


def write_changelog_template(path, source_name, version, wnpp_bugs=None):
    if wnpp_bugs:
        closes = " Closes: " + ", ".join([("#%d" % (bug,)) for bug in wnpp_bugs])
    else:
        closes = ""
    cl = Changelog()
    cl.new_block(
        package=source_name,
        version=version,
        distributions="UNRELEASED",
        urgency="low",
        changes=["", "  * Initial release." + closes, ""],
        author="%s <%s>" % get_maintainer(),
        date=format_date(),
    )
    with open(path, "w") as f:
        f.write(cl.__str__().strip("\n") + "\n")


async def find_archived_wnpp_bugs(source_name):
    try:
        from .udd import connect_udd_mirror
    except ModuleNotFoundError:
        warnings.warn("asyncpg not available, unable to find wnpp bugs.")
        return []
    conn = await connect_udd_mirror()
    return [
        row[0]
        for row in await conn.fetch(
            """\
select id from archived_bugs where package = 'wnpp' and
title like 'ITP: ' || $1 || ' -- %' OR
title like 'RFP: ' || $1 || ' -- %'
""",
            source_name,
        )
    ]


async def find_wnpp_bugs(source_name):
    try:
        from .udd import connect_udd_mirror
    except ModuleNotFoundError:
        warnings.warn("asyncpg not available, unable to find wnpp bugs.")
        return []
    conn = await connect_udd_mirror()
    return [
        row[0]
        for row in await conn.fetch(
            """\
select id from wnpp where source = $1 and type in ('ITP', 'RFP')
""",
            source_name,
        )
    ]


MINIMUM_CERTAINTY = "possible"  # For now..


class DebianDirectoryExists(Exception):
    """A Debian Directory already exists."""

    def __init__(self, path):
        self.path = path


def go_import_path_from_repo(repo_url):
    parsed_url = urlparse(repo_url)
    p = parsed_url.hostname + parsed_url.path.rstrip('/')
    if p.endswith(".git"):
        p = p[:-4]
    return p


def enable_dh_addon(source, addon):
    source["Build-Depends"] = ensure_some_version(
        source["Build-Depends"], "dh-sequence-%s" % addon
    )


def setup_debhelper(wt, debian_path, source, compat_release, addons=None, env=None, buildsystem=None):
    source["Build-Depends"] = ensure_exact_version(
            source.get("Build-Depends", ""),
            "debhelper-compat",
            str(maximum_debhelper_compat_version(compat_release)))
    for addon in addons or []:
        enable_dh_addon(source, addon)
    write_debhelper_rules_template(
        wt.abspath(os.path.join(debian_path, "rules")),
        buildsystem=buildsystem,
        env=(env or {}),
    )


def import_upstream_version_from_dist(
        wt, subpath, source_name, upstream_version,
        session, create_dist=None):
    from breezy.plugins.debian import default_orig_dir
    from breezy.plugins.debian.util import debuild_config
    from breezy.plugins.debian.merge_upstream import get_tarballs, do_import
    from breezy.plugins.debian.upstream.branch import UpstreamBranchSource
    import tempfile

    if create_dist is None:
        def create_dist(tree, package, version, target_dir):
            os.environ['SETUPTOOLS_SCM_PRETEND_VERSION'] = version
            try:
                with session:
                    # TODO(jelmer): set include_controldir=True to make
                    # setuptools_scm happy?
                    return ogni_create_dist(
                        session, tree, target_dir,
                        include_controldir=False,
                        subdir=(package or "package"),
                        cleanup=False)
            except NoBuildToolsFound:
                logging.info(
                    "No build tools found, falling back to simple export.")
                return None
            except NotImplementedError:
                logging.info(
                    "Build system does not support dist, falling back "
                    "to export.")
                return None
            except DetailedFailure as e:
                raise DistCreationFailed(str(e), e.error)
            except UnidentifiedError as e:
                raise DistCreationFailed(str(e))

    config = debuild_config(wt, subpath)
    upstream_source = UpstreamBranchSource.from_branch(
        wt.branch, config=config, local_dir=wt.controldir,
        create_dist=create_dist, snapshot=False)
    tag_names = {}
    with tempfile.TemporaryDirectory() as target_dir:
        locations = upstream_source.fetch_tarballs(
            source_name, upstream_version, target_dir, components=[None])
        orig_dir = config.orig_dir or default_orig_dir
        tarball_filenames = get_tarballs(
            orig_dir, wt, source_name, upstream_version, locations)
        upstream_revisions = upstream_source\
            .version_as_revisions(source_name, upstream_version)
        files_excluded = None
        imported_revids = do_import(
            wt, subpath, tarball_filenames, source_name, upstream_version,
            current_version=None, upstream_branch=wt.branch,
            upstream_revisions=upstream_revisions,
            merge_type=None, files_excluded=files_excluded)
        pristine_revids = {}
        for (component, tag_name, revid, pristine_tar_imported) in imported_revids:
            pristine_revids[component] = revid
            tag_names[component] = tag_name

    upstream_branch_name = "upstream"
    try:
        wt.controldir.create_branch(upstream_branch_name).generate_revision_history(
            pristine_revids[None]
        )
    except AlreadyBranchError:
        logging.info("Upstream branch already exists; not creating.")
    else:
        logging.info("Created upstream branch.")

    return pristine_revids, tag_names, upstream_branch_name


class ResetOnFailure(object):

    def __init__(self, wt, subpath=None):
        self.wt = wt
        self.subpath = subpath

    def __enter__(self):
        check_clean_tree(self.wt, self.wt.basis_tree(), self.subpath)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            reset_tree(self.wt, self.wt.basis_tree(), self.subpath)
        return False


def process_setup_py(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    source["Rules-Requires-Root"] = "no"
    source["Standards-Version"] = latest_standards_version()
    setup_debhelper(
        wt, debian_path,
        source, compat_release=compat_release,
        addons=["python3"],
        buildsystem="pybuild")
    source["Testsuite"] = "autopkgtest-pkg-python"
    # TODO(jelmer): check whether project supports python 3
    source["Build-Depends"] = ensure_some_version(
        source["Build-Depends"], "python3-all")
    if buildsystem.build_backend in ("flit.build_api", "flit_core.build_api"):
        source["Build-Depends"] = ensure_some_version(
            source["Build-Depends"], "flit")
        source["Build-Depends"] = ensure_some_version(
            source["Build-Depends"], "python3-toml")
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    # We're going to be running the testsuite as part of the build,
    # so import the test dependencies too.
    import_build_deps(source, test_deps)
    upstream_name = metadata['Name']
    if upstream_name.startswith('python-'):
        upstream_name = upstream_name[len('python-'):]
    source['Source'] = "python-%s" % upstream_name.lower().replace('_', '-')
    control.add_binary({
            "Package": "python3-%s" % upstream_name.lower().replace('_', '-'),
            "Depends": "${python3:Depends}",
            "Architecture": "all",
        }
    )
    return control


def process_maven(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    source["Rules-Requires-Root"] = "no"
    source["Standards-Version"] = latest_standards_version()
    setup_debhelper(
        wt, debian_path,
        source, compat_release=compat_release,
        buildsystem="maven")
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    upstream_name = metadata['Name']
    source['Source'] = upstream_name
    control.add_binary({
            "Package": "lib%s-java" % upstream_name,
            "Depends": "${java:Depends}",
            "Architecture": "all",
        }
    )
    return control


def process_npm(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    setup_debhelper(
        wt, debian_path,
        source, compat_release=compat_release, addons=["nodejs"])
    upstream_name = metadata['Name'].strip('@').replace('/', '-').replace('_', '-').replace('@', '').lower()
    source['Source'] = "node-%s" % upstream_name
    source["Rules-Requires-Root"] = "no"
    source["Standards-Version"] = latest_standards_version()
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    control.add_binary(
        {"Package": "node-%s" % upstream_name, "Architecture": "all"})
    source["Testsuite"] = "autopkgtest-pkg-nodejs"
    return control


def perl_package_name(upstream_name):
    if upstream_name.startswith('lib'):
        upstream_name = upstream_name[len('lib'):]
    return "lib%s-perl" % upstream_name.replace('::', '-').replace('_', '').lower()


def process_dist_zilla(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    upstream_name = metadata['Name']
    source['Source'] = perl_package_name(upstream_name)
    source["Rules-Requires-Root"] = "no"
    source['Testsuite'] = 'autopkgtest-pkg-perl'
    source["Standards-Version"] = latest_standards_version()
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    setup_debhelper(
        wt, debian_path,
        source, compat_release=compat_release,
        addons=["dist-zilla"])
    control.add_binary(
        {"Package": source['Source'],
         "Depends": "${perl:Depends}",
         "Architecture": "all"
         })
    return control


def process_perl_build_tiny(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    upstream_name = metadata['Name']
    source['Source'] = perl_package_name(upstream_name)
    source["Rules-Requires-Root"] = "no"
    source['Testsuite'] = 'autopkgtest-pkg-perl'
    source["Standards-Version"] = latest_standards_version()
    source["Build-Depends"] = "libmodule-build-perl"
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    setup_debhelper(wt, debian_path, source, compat_release=compat_release)
    control.add_binary(
        {"Package": source['Source'],
         "Depends": "${perl:Depends}",
         "Architecture": "all"
         })
    return control


def process_golang(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    source["Rules-Requires-Root"] = "no"
    source["Standards-Version"] = latest_standards_version()
    source["XS-Go-Import-Path"] = go_import_path_from_repo(
        metadata["Repository"]
    )
    if "Repository-Browse" in metadata:
        source["Homepage"] = metadata["Repository-Browse"]
    source["Section"] = "devel"
    parsed_url = urlparse(metadata["Repository"])
    hostname = parsed_url.hostname
    if hostname == "github.com":
        hostname = "github"
    if hostname == "gopkg.in":
        hostname = "gopkg"
    path = parsed_url.path.rstrip('/').replace("/", "-")
    if path.endswith('.git'):
        path = path[:-4]
    godebname = (hostname + path).replace("_", "-").lower()
    source['Source'] = "golang-%s" % godebname
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    source["Testsuite"] = "autopkgtest-pkg-go"
    dh_env = {}
    if os.path.isdir("examples"):
        dh_env["DH_GOLANG_EXCLUDES"] = "examples/"
    setup_debhelper(
        wt, debian_path,
        source, compat_release=compat_release,
        addons=["golang"],
        buildsystem="golang",
        env=dh_env)
    # TODO(jelmer): Add --builddirectory=_build to dh arguments
    control.add_binary({
        "Package": "golang-%s-dev" % godebname,
        "Architecture": "all",
        "Multi-Arch": "foreign",
        })
    return control


def process_r(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source

    if metadata.get('Archive') == 'CRAN':
        archive = 'cran'
    elif metadata.get('Archive') == 'Bioconductor':
        archive = 'bioc'
    else:
        archive = 'other'

    source["Source"] = "r-%s-%s" % (archive, metadata['Name'].lower())
    source["Rules-Requires-Root"] = "no"
    source["Build-Depends"] = "dh-r, r-base-dev"
    source["Standards-Version"] = latest_standards_version()
    source["Testsuite"] = "autopkgtest-pkg-r"
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    setup_debhelper(
        wt, debian_path, source, compat_release=compat_release,
        buildsystem="R")
    # For now, just assume a single binary package that is architecture-dependent.
    control.add_binary({
        "Package": "r-%s-%s" % (archive, metadata['Name'].lower()),
        "Architecture": 'any',
        'Depends': '${R:Depends}, ${shlibs:Depends}, ${misc:Depends}',
        'Recommends': '${R:Recommends}',
        'Suggests': '${R:Suggests}',
        })
    return control


def process_octave(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source

    source["Source"] = "octave-%s" % metadata['Name'].lower()
    source["Rules-Requires-Root"] = "no"
    source["Build-Depends"] = "dh-octave"
    source["Standards-Version"] = latest_standards_version()
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    setup_debhelper(
        wt, debian_path, source, compat_release=compat_release,
        buildsystem="octave", addons=['octave'])
    # For now, just assume a single binary package that is architecture-independent.
    control.add_binary({
        "Package": "octave-%s" % metadata['Name'].lower(),
        "Architecture": 'all',
        'Depends': '${octave:Depends}, ${misc:Depends}',
        'Description': '${octave:Upstream-Description}',
        })
    return control


def process_default(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    control = es.enter_context(ControlEditor.create(wt.abspath(os.path.join(debian_path, 'control'))))
    source = control.source
    upstream_name = metadata['Name']
    source_name = source_name_from_upstream_name(upstream_name)
    if source_name is None:
        raise SourceNameUnknown(upstream_name)
    source["Source"] = source_name
    source["Rules-Requires-Root"] = "no"
    source["Standards-Version"] = latest_standards_version()
    build_deps, test_deps = get_project_wide_deps(
        session, wt, subpath, buildsystem, buildsystem_subpath)
    import_build_deps(source, build_deps)
    setup_debhelper(
        wt, debian_path,
        source, compat_release=compat_release)
    # For now, just assume a single binary package that is architecture-dependent.
    for binary_name, arch in [(source['Source'], "any")]:
        control.add_binary({"Package": binary_name, "Architecture": arch})
    return control


def process_cargo(es, session, wt, subpath, debian_path, metadata, compat_release, buildsystem, buildsystem_subpath):
    from debmutate.debcargo import DebcargoControlShimEditor
    upstream_name = metadata['Name']
    control = es.enter_context(DebcargoControlShimEditor.from_debian_dir(wt.abspath(debian_path), upstream_name))
    control.debcargo_editor['overlay'] = '.'
    return control


PROCESSORS = {
    "setup.py": process_setup_py,
    "npm": process_npm,
    "maven": process_maven,
    "dist-zilla": process_dist_zilla,
    "dist-inkt": process_dist_zilla,
    "perl-build-tiny": process_perl_build_tiny,
    "cargo": process_cargo,
    "golang": process_golang,
    "R": process_r,
    "octave": process_octave,
    }


def source_name_from_directory_name(path):
    d = os.path.dirname(path)
    if '-' in d:
        return d.split('-')
    return d


class DebianizeResult(object):
    """Debianize result."""

    def __init__(self, upstream_branch_name, tag_names, upstream_version):
        self.upstream_branch_name = upstream_branch_name
        self.tag_names = tag_names
        self.upstream_version = upstream_version


def get_project_wide_deps(session, wt, subpath, buildsystem, buildsystem_subpath):
    build_deps = []
    test_deps = []

    with session:
        external_dir, internal_dir = session.setup_from_vcs(
            wt, os.path.join(subpath, buildsystem_subpath))

        from ognibuild.debian.udd import popcon_tie_breaker
        from ognibuild.debian.build_deps import BuildDependencyTieBreaker
        apt_resolver = AptResolver.from_session(
            session, tie_breakers=[
                BuildDependencyTieBreaker.from_session(session),
                popcon_tie_breaker,
                ])
        build_fixers = [InstallFixer(apt_resolver)]
        session.chdir(internal_dir)
        try:
            upstream_deps = list(buildsystem.get_declared_dependencies(
                session, build_fixers))
        except NotImplementedError:
            logging.warning('Unable to obtain declared dependencies.')
        else:
            for kind, dep in upstream_deps:
                apt_dep = apt_resolver.resolve(dep)
                if apt_dep is None:
                    logging.warning(
                        'Unable to map upstream requirement %s (kind %s) '
                        'to a Debian package', dep, kind)
                    continue
                logging.debug('Mapped %s (kind: %s) to %s', dep, kind, apt_dep)
                if kind in ('core', 'build'):
                    build_deps.append(apt_dep)
                if kind in ('core', 'test', ):
                    test_deps.append(apt_dep)
    return (build_deps, test_deps)


def import_build_deps(source, build_deps):
    for build_dep in build_deps:
        for rel in build_dep.relations:
            source["Build-Depends"] = ensure_relation(
                source.get("Build-Depends", ""),
                PkgRelation.str([rel]))


def import_upstream_dist(pristine_tar_source, upstream_tree, subpath, source_name, upstream_version, session, create_dist=None):
    if pristine_tar_source.has_version(source_name, upstream_version):
        logging.warning(
            'Upstream version %s/%s already imported.',
            source_name, upstream_version)
        pristine_revids = pristine_tar_source\
            .version_as_revisions(source_name, upstream_version)
        upstream_branch_name = None
        tag_names = {}
    else:
        (pristine_revids, tag_names,
         upstream_branch_name) = import_upstream_version_from_dist(
            upstream_tree, subpath,
            source_name, upstream_version,
            session=session,
            create_dist=create_dist)

    return pristine_revids[None], upstream_branch_name, tag_names


def generic_get_source_name(wt, metadata):
    try:
        source_name = source_name_from_upstream_name(metadata['Name'])
    except KeyError:
        source_name = None
    else:
        if not valid_debian_package_name(source_name):
            source_name = None
    if source_name is None:
        source_name = source_name_from_directory_name(wt.basedir)
        if not valid_debian_package_name(source_name):
            source_name = None
    return source_name


def get_upstream_version(branch, upstream_revision, metadata):
    from breezy.plugins.debian.upstream.branch import (
        upstream_branch_version,
        upstream_version_add_revision,
    )

    upstream_version = upstream_branch_version(
        branch, upstream_revision, metadata.get("Name")
    )
    if upstream_version is None and "X-Version" in metadata:
        # They haven't done any releases yet. Assume we're ahead of
        # the next announced release?
        next_upstream_version = debian_upstream_version(metadata["X-Version"])
        upstream_version = upstream_version_add_revision(
            branch, next_upstream_version, upstream_revision, "~"
        )
    if upstream_version is None:
        upstream_version = upstream_version_add_revision(
            branch, "0", upstream_revision, "+"
        )
        logging.warning(
            "Unable to determine upstream version, using %s.",
            upstream_version)
    return upstream_version


def find_wnpp_bugs_harder(source_name, upstream_name):
    import asyncio

    loop = asyncio.get_event_loop()
    wnpp_bugs = loop.run_until_complete(find_wnpp_bugs(source_name))
    if not wnpp_bugs and source_name != upstream_name:
        wnpp_bugs = loop.run_until_complete(find_wnpp_bugs(upstream_name))
    if not wnpp_bugs:
        wnpp_bugs = loop.run_until_complete(
            find_archived_wnpp_bugs(source_name)
        )
        if wnpp_bugs:
            logging.warning(
                "Found archived ITP/RFP bugs for %s: %r", source_name, wnpp_bugs
            )
        else:
            logging.warning(
                "No relevant WNPP bugs found for %s", source_name)
    else:
        logging.info("Found WNPP bugs for %s: %r", source_name, wnpp_bugs)

    return wnpp_bugs


def debianize(  # noqa: C901
    wt: WorkingTree, subpath: str,
    upstream_branch: Branch, upstream_subpath: str,
    use_inotify: Optional[bool] = None,
    diligence: int = 0,
    trust: bool = False,
    check: bool = False,
    net_access: bool = True,
    force_subprocess: bool = False,
    force_new_directory: bool = False,
    compat_release: Optional[str] = None,
    minimum_certainty: str = MINIMUM_CERTAINTY,
    consult_external_directory: bool = True,
    verbose: bool = False,
    schroot: Optional[str] = None,
    create_dist=None,
    committer: Optional[str] = None
):
    if committer is None:
        committer = get_committer(wt)

    debian_path = osutils.pathjoin(subpath, "debian")
    if wt.has_filename(debian_path) and list(os.listdir(wt.abspath(debian_path))):
        if force_new_directory:
            shutil.rmtree(wt.abspath(debian_path))
            wt.commit(
                'Remove old debian directory', specific_files=[debian_path],
                reporter=NullCommitReporter())
        else:
            raise DebianDirectoryExists(wt.abspath(subpath))

    metadata_items = []

    def import_metadata_from_tree(t, sp):
        metadata_items.extend(guess_upstream_info(t.abspath(sp), trust_package=trust))
        return summarize_upstream_metadata(
            metadata_items, t.abspath(sp), net_access=net_access,
            consult_external_directory=consult_external_directory,
            check=check)

    metadata = import_metadata_from_tree(wt, subpath)

    if not verbose:
        commit_reporter = NullCommitReporter()
    else:
        commit_reporter = None

    with wt.lock_write():
        with contextlib.ExitStack() as es:
            es.enter_context(ResetOnFailure(wt, subpath=subpath))

            if not wt.has_filename(debian_path):
                wt.mkdir(debian_path)

            # TODO(jelmer): Support resetting to e.g. last upstream release
            upstream_revision = upstream_branch.last_revision()
            upstream_version = get_upstream_version(
                upstream_branch, upstream_revision, metadata)

            if wt.last_revision() == upstream_revision:
                # If at all possible, try to avoid copying
                upstream_tree = wt
            else:
                upstream_tree = upstream_branch.repository.revision_tree(upstream_revision)

            if schroot is None:
                session = PlainSession()
            else:
                logging.info('Using schroot %s', schroot)
                session = SchrootSession(schroot)

            source_name = generic_get_source_name(wt, metadata)

            pristine_tar_source = get_pristine_tar_source(wt, wt.branch)
            upstream_dist_revid, upstream_branch_name, tag_names = import_upstream_dist(
                pristine_tar_source, upstream_tree, upstream_subpath, source_name,
                upstream_version, session, create_dist)

            if wt.branch.last_revision() != upstream_dist_revid:
                wt.pull(
                    wt.branch, overwrite=True,
                    stop_revision=upstream_dist_revid)

                # Gather metadata items again now that we're at the correct
                # revision
                metadata = import_metadata_from_tree(wt, subpath)

            os.chdir(wt.abspath(subpath))

            version = Version(upstream_version + "-1")

            buildsystem_subpath, buildsystem = get_buildsystem(wt.abspath(subpath))

            if buildsystem:
                try:
                    process = PROCESSORS[buildsystem.name]
                except KeyError:
                    process = process_default
            else:
                process = process_default

            logging.info('Creating core packaging using %s', process.__name__)

            control = process(
                es, session,
                wt, subpath, debian_path,
                metadata=metadata, compat_release=compat_release,
                buildsystem=buildsystem,
                buildsystem_subpath=buildsystem_subpath)

            source = control.source

            if not valid_debian_package_name(source['Source']):
                raise SourcePackageNameInvalid(source['Source'])

            if net_access:
                wnpp_bugs = find_wnpp_bugs_harder(source['Source'], metadata.get('Name'))
            else:
                wnpp_bugs = None

            write_changelog_template(
                wt.abspath(os.path.join(debian_path, "changelog")),
                source["Source"],
                version,
                wnpp_bugs,
            )

        wt.smart_add([wt.abspath(debian_path)])
        wt.commit(
            "Create debian/ directory",
            allow_pointless=False,
            committer=committer,
            reporter=commit_reporter,
        )

    with wt.lock_write():

        lintian_fixers = available_lintian_fixers(force_subprocess=force_subprocess)

        run_lintian_fixers(
            wt,
            list(lintian_fixers),
            update_changelog=False,
            compat_release=compat_release,
            verbose=verbose,
            minimum_certainty=minimum_certainty,
            trust_package=trust,
            allow_reformatting=True,
            use_inotify=use_inotify,
            subpath=subpath,
            net_access=net_access,
            opinionated=True,
            diligence=diligence,
        )

        try:
            update_offical_vcs(wt, subpath=subpath, committer=committer)
        except VcsAlreadySpecified:
            pass
        except NoVcsLocation:
            logging.debug(
                'No public VCS location specified and unable to guess it '
                'based on maintainer e-mail.')
        except FileNotFoundError:
            logging.info(
                'No control file or debcargo.toml file, '
                'not setting vcs information.')

    return DebianizeResult(
        upstream_branch_name=upstream_branch_name,
        tag_names=tag_names,
        upstream_version=upstream_version)


def main(argv=None):
    import argparse

    import breezy  # noqa: E402

    breezy.initialize()
    import breezy.git  # noqa: E402
    import breezy.bzr  # noqa: E402

    parser = argparse.ArgumentParser(prog="debianize")
    parser.add_argument(
        "--directory", "-d",
        metavar="DIRECTORY",
        help="directory to run in",
        type=str,
        default=".",
    )
    parser.add_argument(
        "--disable-inotify", action="store_true", default=False, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + version_string
    )
    parser.add_argument("--compat-release", type=str, help=argparse.SUPPRESS)
    parser.add_argument(
        "--verbose", help="be verbose", action="store_true", default=False
    )
    parser.add_argument(
        "--disable-net-access",
        help="Do not probe external services.",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--diligent",
        action="count",
        default=0,
        dest="diligence",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--trust",
        action="store_true",
        help="Whether to allow running code from the package.",
    )
    parser.add_argument(
        "--consult-external-directory",
        action="store_true",
        help="Pull in external (not maintained by upstream) directory data",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check guessed metadata against external sources.",
    )
    parser.add_argument(
        "--force-subprocess", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--force-new-directory", action="store_true",
        help="Create a new debian/ directory even if one already exists.")
    parser.add_argument(
        "--iterate-fix", "-x", action="store_true",
        help="Invoke deb-fix-build afterwards to build package and add "
        "missing dependencies.")
    parser.add_argument(
        "--schroot", type=str,
        help="Schroot to use for building and apt archive access")
    parser.add_argument(
        "--build-command",
        type=str,
        help="Build command (used for --iterate-fix)",
        default=(DEFAULT_BUILDER + " -A -s -v"),
    )
    parser.add_argument(
        "--max-build-iterations",
        type=int,
        default=50,
        help=argparse.SUPPRESS)
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Attempt to package dependencies if they are not yet packaged.")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    compat_release = args.compat_release
    if compat_release is None:
        import distro_info

        debian_info = distro_info.DebianDistroInfo()
        compat_release = debian_info.stable()

    wt, subpath = WorkingTree.open_containing(args.directory)

    # For now...
    upstream_branch = wt.branch
    upstream_subpath = subpath

    use_inotify = ((False if args.disable_inotify else None),)
    with wt.lock_write():
        try:
            debianize(
                wt, subpath,
                upstream_branch, upstream_subpath,
                use_inotify=use_inotify,
                diligence=args.diligence,
                trust=args.trust,
                check=args.check,
                net_access=not args.disable_net_access,
                force_new_directory=args.force_new_directory,
                force_subprocess=args.force_subprocess,
                compat_release=compat_release,
                consult_external_directory=args.consult_external_directory,
                verbose=args.verbose,
                schroot=args.schroot
            )
        except PendingChanges:
            logging.info("%s: Please commit pending changes first.", wt.basedir)
            return 1
        except DebianDirectoryExists as e:
            logging.info(
                "%s: A debian directory already exists. " "Run lintian-brush instead?",
                e.path,
            )
            return 1
        except SourcePackageNameInvalid as e:
            logging.info("Unable to sanitize source package name: %s", e.source)
            return 1
        except DistCreationFailed as e:
            logging.fatal('Dist tarball creation failed: %s', e.inner)
            return 1

    if args.iterate_fix:
        import tempfile
        from ognibuild.debian.fix_build import (
            DetailedDebianBuildFailure,
            UnidentifiedDebianBuildError,
            build_incrementally,
            )
        if args.schroot is None:
            session = PlainSession()
        else:
            logging.info('Using schroot %s', args.schroot)
            session = SchrootSession(args.schroot)

        with contextlib.ExitStack() as es:
            es.enter_context(session)
            apt = AptManager.from_session(session)

            def do_build():
                output_directory = es.enter_context(tempfile.TemporaryDirectory())
                return build_incrementally(
                    wt,
                    apt,
                    None,
                    None,
                    output_directory,
                    args.build_command,
                    build_changelog_entry=None,
                    committer=None,
                    update_changelog=False,
                    max_iterations=args.max_build_iterations,
                )

            try:
                (changes_names, cl_version) = do_build()
            except DetailedDebianBuildFailure as e:
                if e.phase is None:
                    phase = 'unknown phase'
                elif len(e.phase) == 1:
                    phase = e.phase[0]
                else:
                    phase = '%s (%s)' % (e.phase[0], e.phase[1])
                logging.fatal('Error during %s: %s', phase, e.error)
                return 1
            except UnidentifiedDebianBuildError as e:
                if e.phase is None:
                    phase = 'unknown phase'
                elif len(e.phase) == 1:
                    phase = e.phase[0]
                else:
                    phase = '%s (%s)' % (e.phase[0], e.phase[1])
                logging.fatal('Error during %s: %s', phase, e.description)
                return 1
            logging.info('Built %r.', changes_names)

    return 0


if __name__ == "__main__":
    sys.exit(main())
