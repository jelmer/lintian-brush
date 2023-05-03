#!/usr/bin/python3
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

"""Utility functions for applying multi-arch hints."""

import contextlib
import json
import logging
import os
import re
import sys
import time
from typing import Optional, Dict, List, Any, Union

from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from breezy.workspace import (
    WorkspaceDirty,
    check_clean_tree,
    )

from lintian_brush import (
    Fixer,
    NoChanges,
    NotDebianPackage,
    FixerResult,
    min_certainty,
    USER_AGENT,
    SUPPORTED_CERTAINTIES,
    DEFAULT_URLLIB_TIMEOUT,
    certainty_sufficient,
    get_committer,
    get_dirty_tracker,
    run_lintian_fixer,
    version_string,
    control_files_in_root,
    control_file_present,
    is_debcargo_package,
)
from debmutate.control import (
    ControlEditor,
    format_relations,
    parse_relations,
)
from debmutate.reformatting import GeneratedFile, FormattingUnpreservable


DEFAULT_VALUE_MULTIARCH_HINT = 100
MULTIARCH_HINTS_VALUE = {
    "ma-foreign": 20,
    "file-conflict": 50,
    "ma-foreign-library": 20,
    "dep-any": 20,
    "ma-same": 20,
    "arch-all": 20,
}


def calculate_value(hints):
    return sum(map(MULTIARCH_HINTS_VALUE.__getitem__, hints)) + (
        DEFAULT_VALUE_MULTIARCH_HINT
    )


MULTIARCH_HINTS_URL = "https://dedup.debian.net/static/multiarch-hints.yaml.xz"


def parse_multiarch_hints(f):
    """Parse a multi-arch hints file.

    Args:
      f: File-like object to read from
    Returns:
      dictionary mapping binary package names to lists of hints
    """
    from ruamel.yaml import YAML

    yaml = YAML(typ="safe")
    data = yaml.load(f)
    if data.get("format") != "multiarch-hints-1.0":
        raise ValueError("invalid file format: %r" % data.get("format"))
    return data["hints"]


def multiarch_hints_by_binary(hints) -> Dict[str, List[Any]]:
    ret: Dict[str, List[Any]] = {}
    for entry in hints:
        ret.setdefault(entry["binary"], []).append(entry)
    return ret


def multiarch_hints_by_source(hints) -> Dict[str,  List[Any]]:
    ret: Dict[str, List[Any]] = {}
    for entry in hints:
        if "source" not in entry:
            continue
        ret.setdefault(entry["source"], []).append(entry)
    return ret


def cache_download_multiarch_hints(url=MULTIARCH_HINTS_URL):
    """Load multi-arch hints from a URL, but use cached version if available.
    """
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if not cache_home:
        cache_home = os.path.expanduser("~/.cache")
    cache_dir = os.path.join(cache_home, "lintian-brush")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except PermissionError:
        local_hints_path = None
        last_modified = None
        logging.warning("Unable to create %s; not caching.", cache_dir)
    else:
        local_hints_path = os.path.join(cache_dir, "multiarch-hints.yml")
        try:
            last_modified = os.path.getmtime(local_hints_path)
        except FileNotFoundError:
            last_modified = None
    try:
        with download_multiarch_hints(url=url, since=last_modified) as f:
            if local_hints_path is None:
                return f
            logging.info("Downloading new version of multi-arch hints.")
            with open(local_hints_path, "wb") as c:
                c.writelines(f)
    except HTTPError as e:
        if e.status != 304:
            raise
    except URLError:
        raise
    assert local_hints_path is not None
    return open(local_hints_path, "rb")  # noqa: SIM115


@contextlib.contextmanager
def download_multiarch_hints(url=MULTIARCH_HINTS_URL,
                             since: Optional[Union[float, int]] = None):
    """Load multi-arch hints from a URL.

    Args:
      url: URL to read from
      since: Last modified timestamp
    Returns:
      multi-arch hints file
    """
    headers = {"User-Agent": USER_AGENT}
    if since is not None:
        headers["If-Modified-Since"] = time.strftime(
            "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(since)
        )

    with urlopen(Request(url, headers=headers),
                 timeout=DEFAULT_URLLIB_TIMEOUT) as f:
        if url.endswith(".xz"):
            import lzma

            # It would be nicer if there was a content-type, but there isn't
            # :-(
            f = lzma.LZMAFile(f)
        yield f


def apply_hint_ma_foreign(binary, hint):
    if binary.get("Multi-Arch") != "foreign":
        binary["Multi-Arch"] = "foreign"
        return "Add Multi-Arch: foreign."


def apply_hint_ma_foreign_lib(binary, hint):
    if binary.get("Multi-Arch") == "foreign":
        del binary["Multi-Arch"]
        return "Drop Multi-Arch: foreign."


def apply_hint_file_conflict(binary, hint):
    if binary.get("Multi-Arch") == "same":
        del binary["Multi-Arch"]
        return "Drop Multi-Arch: same."


def apply_hint_dep_any(binary, hint):
    m = re.match(
        "(.*) could have its dependency on (.*) annotated with :any",
        hint["description"],
    )
    if not m or m.group(1) != binary["Package"]:
        raise ValueError(
            "unable to parse hint description: %r"
            % hint["description"])
    dep = m.group(2)
    if "Depends" not in binary:
        return None
    changed = False
    relations = parse_relations(binary["Depends"])
    for entry in relations:
        (head_whitespace, relation, tail_whitespace) = entry
        if not isinstance(relation, str):  # formatting
            for r in relation:
                if r.name == dep and r.archqual != "any":
                    r.archqual = "any"
                    changed = True
    if not changed:
        return None
    binary["Depends"] = format_relations(relations)
    return "Add :any qualifier for %s dependency." % dep


def apply_hint_ma_same(binary, hint) -> Optional[str]:
    if binary.get("Multi-Arch") == "same":
        return None
    binary["Multi-Arch"] = "same"
    return "Add Multi-Arch: same."


def apply_hint_arch_all(binary, hint) -> Optional[str]:
    if binary["Architecture"] == "all":
        return None
    binary["Architecture"] = "all"
    return "Make package Architecture: all."


class MultiArchHintApplier:
    def __init__(self, kind, fn, certainty):
        self.kind = kind
        self.fn = fn
        self.certainty = certainty


class MultiArchFixerResult(FixerResult):
    def __init__(self, description, certainty, changes):
        super().__init__(
            description=description, certainty=certainty
        )
        self.changes = changes


def apply_multiarch_hints(hints, minimum_certainty: str = "certain"):
    changes = []
    appliers = {applier.kind: applier for applier in APPLIERS}

    with ControlEditor() as editor:
        for binary in editor.binaries:
            for hint in hints.get(binary["Package"], []):
                kind = hint["link"].rsplit("#", 1)[1]
                applier = appliers[kind]
                if not certainty_sufficient(
                        applier.certainty, minimum_certainty):
                    continue
                description = applier.fn(binary, hint)
                if description:
                    changes.append(
                        (binary, hint, description, applier.certainty))

    return changes


def changes_by_description(changes) -> Dict[str, List[str]]:
    by_description: Dict[str, List[str]] = {}
    for (binary, _hint, description, _certainty) in changes:
        by_description.setdefault(description, []).append(binary["Package"])
    return by_description


class MultiArchHintFixer(Fixer):
    def __init__(self, hints):
        super().__init__(name="multiarch-hints")
        self._hints = hints

    def run(
        self,
        basedir,
        package,
        current_version,
        compat_release,
        minimum_certainty=None,
        trust_package=False,
        allow_reformatting=False,
        net_access=True,
        opinionated=False,
        diligence=0,
    ):
        if not net_access:
            # This should never happen - perhaps if something else imported and
            # used this class?
            raise NoChanges(self)
        old_cwd = os.getcwd()
        try:
            os.chdir(basedir)
            changes = apply_multiarch_hints(self._hints, minimum_certainty)
        finally:
            os.chdir(old_cwd)

        overall_certainty = min_certainty(
            [certainty for (binary, hint, description, certainty) in changes]
        )
        by_description = changes_by_description(changes)
        overall_description = ["Apply multi-arch hints."]
        for description, binaries in by_description.items():
            overall_description.append(
                "+ {}: {}".format(", ".join(sorted(binaries)), description)
            )
        return MultiArchFixerResult(
            "\n".join(overall_description),
            certainty=overall_certainty, changes=changes
        )


APPLIERS = [
    MultiArchHintApplier(
        "ma-foreign", apply_hint_ma_foreign, "certain"),
    MultiArchHintApplier(
        "file-conflict", apply_hint_file_conflict, "certain"),
    MultiArchHintApplier(
        "ma-foreign-library", apply_hint_ma_foreign_lib, "certain"),
    MultiArchHintApplier("dep-any", apply_hint_dep_any, "certain"),
    MultiArchHintApplier("ma-same", apply_hint_ma_same, "certain"),
    MultiArchHintApplier("arch-all", apply_hint_arch_all, "possible"),
]


def versions_dict() -> Dict[str, str]:
    import lintian_brush
    import debmutate
    import debian
    return {
        'lintian-brush': lintian_brush.version_string,
        'debmutate': debmutate.version_string,
        'debian': debian.__version__,
    }


def report_okay(code: str, description: str):
    if os.environ.get('SVP_API') == '1':
        with open(os.environ['SVP_RESULT'], 'w') as f:
            json.dump({
                'versions': versions_dict(),
                'result_code': code,
                'description': description}, f)
    logging.info('%s', description)


def report_fatal(code: str, description: str, transient: bool = False) -> None:
    if os.environ.get('SVP_API') == '1':
        with open(os.environ['SVP_RESULT'], 'w') as f:
            json.dump({
                'versions': versions_dict(),
                'result_code': code,
                'transient': transient,
                'description': description}, f)
    logging.fatal('%s', description)


def main(argv=None):  # noqa: C901
    import argparse
    from breezy.workingtree import WorkingTree

    import breezy  # noqa: E402
    from breezy.errors import NotBranchError

    breezy.initialize()  # type: ignore
    import breezy.git  # noqa: E402
    import breezy.bzr  # noqa: E402

    from .config import Config

    parser = argparse.ArgumentParser(prog="multi-arch-fixer")
    parser.add_argument(
        "--directory",
        metavar="DIRECTORY",
        help="directory to run in",
        type=str,
        default=".",
    )
    parser.add_argument(
        "--disable-inotify", action="store_true", default=False,
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--identity",
        help="Print user identity that would be used when committing",
        action="store_true",
        default=False,
    )
    # Hide the minimum-certainty option for the moment.
    parser.add_argument(
        "--minimum-certainty",
        type=str,
        choices=SUPPORTED_CERTAINTIES,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-update-changelog",
        action="store_false",
        default=None,
        dest="update_changelog",
        help="do not update the changelog",
    )
    parser.add_argument(
        "--update-changelog",
        action="store_true",
        dest="update_changelog",
        help="force updating of the changelog",
        default=None,
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + version_string
    )
    parser.add_argument(
        "--allow-reformatting",
        default=None,
        action="store_true",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    minimum_certainty = args.minimum_certainty
    try:
        wt, subpath = WorkingTree.open_containing(args.directory)
    except NotBranchError:
        logging.error(
            "No version control directory found (e.g. a .git directory).")
        return 1

    if args.identity:
        logging.info('%s', get_committer(wt))
        return 0

    update_changelog = args.update_changelog
    allow_reformatting = args.allow_reformatting
    try:
        cfg = Config.from_workingtree(wt, subpath)
    except FileNotFoundError:
        pass
    else:
        if minimum_certainty is None:
            minimum_certainty = cfg.minimum_certainty()
        if allow_reformatting is None:
            allow_reformatting = cfg.allow_reformatting()
        if update_changelog is None:
            update_changelog = cfg.update_changelog()

    use_inotify = (False if args.disable_inotify else None)
    with contextlib.ExitStack() as es:
        es.enter_context(wt.lock_write())
        try:
            check_clean_tree(wt, wt.basis_tree(), subpath)
        except WorkspaceDirty:
            logging.info("%s: Please commit pending changes first.",
                         wt.basedir)
            return 1

        dirty_tracker = get_dirty_tracker(wt, subpath, use_inotify)
        # Only Breezy >= 3.3.1 has DirtyTracker as a context manager
        if dirty_tracker and hasattr(dirty_tracker, '__enter__'):
            from breezy.dirty_tracker import TooManyOpenFiles
            try:
                es.enter_context(dirty_tracker)
            except TooManyOpenFiles:
                logging.warning(
                    'Too many open files for inotify, not using it.')
                dirty_tracker = None

        try:
            with cache_download_multiarch_hints() as f:
                hints = multiarch_hints_by_binary(parse_multiarch_hints(f))
        except (HTTPError, URLError, TimeoutError) as e:
            report_fatal(
                "multiarch-hints-download-error",
                "Unable to download multiarch hints: %s" % e,
                transient=True)
            return 1

        if control_files_in_root(wt, subpath):
            report_fatal(
                "control-files-in-root",
                "control files live in root rather than debian/ "
                "(LarstIQ mode)",
            )
            return 1

        if is_debcargo_package(wt, subpath):
            report_okay("nothing-to-do", "Package uses debcargo")
            return 0
        if not control_file_present(wt, subpath):
            report_fatal("missing-control-file",
                         "Unable to find debian/control")
            return 1

        try:
            result, summary = run_lintian_fixer(
                wt,
                MultiArchHintFixer(hints),
                update_changelog=update_changelog,
                minimum_certainty=minimum_certainty,
                dirty_tracker=dirty_tracker,
                subpath=subpath,
                allow_reformatting=allow_reformatting,
                net_access=True,
                changes_by="apply-multiarch-hints",
            )
        except NoChanges:
            report_okay("nothing-to-do", "no hints to apply")
            return 0
        except FormattingUnpreservable as e:
            report_fatal(
                "formatting-unpreservable",
                "unable to preserve formatting while editing %s" % e.path,
            )
            if hasattr(e, 'diff'):  # debmutate >= 0.64
                sys.stderr.writelines(e.diff())
            return 1
        except GeneratedFile as e:
            report_fatal(
                "generated-file", "unable to edit generated file: %r" % e)
            return 1
        except NotDebianPackage:
            logging.info("%s: Not a debian package.", wt.basedir)
            return 1
        else:
            applied_hints = []
            hint_names = []
            for (binary, hint, description, certainty) in result.changes:
                hint_names.append(hint["link"].split("#")[-1])
                entry = dict(hint.items())
                hint_names.append(entry["link"].split("#")[-1])
                entry["action"] = description
                entry["certainty"] = certainty
                applied_hints.append(entry)
                logging.info("%s: %s", binary["Package"], description)
            if os.environ.get('SVP_API') == '1':
                with open(os.environ['SVP_RESULT'], 'w') as f:
                    json.dump({
                        'description': "Applied multi-arch hints.",
                        'versions': versions_dict(),
                        'value': calculate_value(hint_names),
                        'commit-message': 'Apply multi-arch hints',
                        'context': {
                            'applied-hints': applied_hints,
                        }}, f)


if __name__ == "__main__":
    sys.exit(main())
