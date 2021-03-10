#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij
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

"""Utility functions for dealing with lintian overrides files."""

from debian.changelog import Version
import os
from typing import Optional, Iterator, Callable, List, Tuple

from debmutate.lintian_overrides import (
    LintianOverridesEditor,
    LintianOverride,
    iter_overrides,
)


def overrides_paths() -> Iterator[str]:
    for path in ["debian/source/lintian-overrides"]:
        if os.path.exists(path):
            yield path
    if os.path.exists("debian"):
        for entry in os.scandir("debian"):
            if entry.name.endswith(".lintian-overrides"):
                yield entry.path


def update_overrides(cb: Callable[[int, LintianOverride], LintianOverride]) -> None:
    """ "Call update_overrides_file on all overrides files.

    Args:
      cb: Callback that modifies overrides; called with an Override object
    """
    for path in overrides_paths():
        update_overrides_file(cb, path=path)


def update_overrides_file(
    cb: Callable[[int, LintianOverride], LintianOverride],
    path: str = "debian/source/lintian-overrides",
) -> bool:
    """Modify the overrides in a file.

    Args:
      cb: Callback that modifies overrides; called with an Override object
        Should return new override or None to delete override.
    Returns:
        Whether the file was modified
    """
    with LintianOverridesEditor(path=path) as editor:
        new_lines = []
        comments: List[str] = []
        for lineno, entry in enumerate(editor.lines, 1):
            if isinstance(entry, LintianOverride):
                entry = cb(lineno, entry)
                if entry is not None:
                    new_lines.extend(comments)
                    new_lines.append(entry)
                comments = []
            else:
                comments.append(entry)
        editor._parsed = new_lines + comments
        return editor.has_changed()


def get_overrides(
    type: Optional[str] = None, package: Optional[str] = None
) -> Iterator[LintianOverride]:
    paths = []
    if type in ("source", None):
        paths.extend(
            ["debian/source/lintian-overrides", "debian/source.lintian-overrides"]
        )
    if type in ("binary", None):
        if package is not None:
            paths.extend(["debian/%s.lintian-overrides" % package])
        elif os.path.isdir("debian"):
            paths.extend(
                [
                    e.path
                    for e in os.scandir("debian")
                    if e.name.endswith(".lintian-overrides")
                ]
            )

    for path in paths:
        try:
            with open(path, "r") as f:
                yield from iter_overrides(f)
        except FileNotFoundError:
            pass


def override_exists(
    tag: str,
    info: Optional[str] = None,
    package: Optional[str] = None,
    type: Optional[str] = None,
    arch: Optional[str] = None,
) -> bool:
    """Check if a particular override exists.

    Args:
      tag: Tag name
      info: Optional info
      package: Package
      type: package type (source, binary)
      arch: Architecture
    """
    for override in get_overrides(type=type, package=package):
        if override.matches(package=package, info=info, tag=tag, arch=arch, type=type):
            return True
    return False


async def get_unused_overrides(
    packages: List[Tuple[str, str]]
) -> List[Tuple[str, str, Version, str]]:
    from .udd import connect_udd_mirror

    udd = await connect_udd_mirror()

    args: List[str] = []
    extra = []
    for (type, name) in packages:
        extra.append(
            "package = $%d AND package_type = $%d" % (len(args) + 1, len(args) + 2)
        )
        args.extend([name, type])

    return list(
        await udd.fetch(
            """\
select package, package_type, package_version, information
from lintian where tag = 'unused-override' AND (%s)"""
            % " OR ".join(extra),
            *args
        )
    )


unused_overrides = None


def remove_unused(control_paragraphs, ignore_tags=None) -> List[LintianOverride]:

    if ignore_tags is None:
        ignore_tags = set()
    packages = []
    for para in control_paragraphs:
        if "Source" in para:
            packages.append(("source", para["Source"]))
        else:
            packages.append(("binary", para["Package"]))
    global unused_overrides
    unused_overrides = None
    removed = []

    def is_unused(override, unused_overrides):
        for unused_override in unused_overrides:
            if override.package not in (None, unused_override[0]):
                continue
            if override.type not in (None, unused_override[1]):
                continue
            if override.info:
                expected_info = "%s %s" % (override.tag, override.info)
            else:
                expected_info = override.tag
            if expected_info != unused_override[3]:
                continue
            return True
        return False

    def drop_override(lineno, override):
        global unused_overrides
        if unused_overrides is None:
            import asyncio

            loop = asyncio.get_event_loop()
            unused_overrides = loop.run_until_complete(get_unused_overrides(packages))
        if is_unused(override, unused_overrides) and override.tag not in ignore_tags:
            removed.append(override)
            return None
        return override

    update_overrides(drop_override)
    return removed


def load_renamed_tags():
    import json

    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "renamed-tags.json")
    )
    if not os.path.isfile(path):
        import pkg_resources

        path = pkg_resources.resource_filename(
            __name__, "lintian-brush/renamed-tags.json"
        )
        if not os.path.isfile(path):
            # Urgh.
            path = "/usr/share/lintian-brush/renamed-tags.json"
    with open(path, "rb") as f:
        return json.load(f)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remove-unused", action="store_true", help="Remove unused overrides."
    )
    args = parser.parse_args()
    if args.remove_unused:
        from debian.deb822 import Deb822
        with open("debian/control", "r") as f:
            removed = remove_unused(Deb822.iter_paragraphs(f))
        print("Removed %d unused overrides" % len(removed))
    else:
        parser.print_usage()
