#!/usr/bin/python3

# TODO(jelmer): Read python3 setup.py dist_info
# TODO(jelmer): Check XS-Go-Import-Path

import logging
import os
import sys

from upstream_ontologist import (
    UpstreamMetadata,
    upstream_metadata_sort_key,
)
from upstream_ontologist.guess import (
    check_upstream_metadata,
    extend_upstream_metadata,
    filter_bad_guesses,
    fix_upstream_metadata,
    guess_upstream_metadata_items,
    update_from_guesses,
)
from upstream_ontologist.vcs import convert_cvs_list_to_str

from lintian_brush import (
    min_certainty,
)
from lintian_brush.fixer import (
    LintianIssue,
    current_package_version,
    meets_minimum_certainty,
    net_access_allowed,
    package_is_native,
    report_result,
    trust_package,
)
from lintian_brush.upstream_metadata import (
    ADDON_ONLY_FIELDS,
    DEP12_FIELDS,
)
from lintian_brush.yaml import (
    YamlUpdater,
    update_ordered_dict,
)


def debian_to_upstream_version(v):
    v = v.upstream_version
    if "~" in v:
        return v.split("~")[0]
    if "+" in v:
        return v.split("+")[0]
    return v


# Don't clutter standard err/standard out
logger = logging.getLogger("upstream_ontologist.extrapolate")
logger.setLevel(logging.ERROR)


def filter_by_tag(orig, changed, fields, tag):
    if all(field in orig for field in fields):
        return

    issue = LintianIssue("source", tag, info="[debian/upstream/metadata]")

    if not all(field in orig for field in fields) and not issue.should_fix():
        for field in fields:
            if field in changed:
                del changed[field]

    if all(field in orig or field in changed for field in fields):
        issue.report_fixed()


if package_is_native():
    # Native package
    sys.exit(0)


current_version = current_package_version()

missing_file_issue = LintianIssue(
    "source", "upstream-metadata-file-is-missing", info=()
)

if (
    not os.path.exists("debian/upstream/metadata")
    and not missing_file_issue.should_fix()
):
    sys.exit(0)


with YamlUpdater("debian/upstream/metadata") as editor:
    if isinstance(editor.code, str):
        sys.exit(0)

    code = dict(editor.code)

    repository = code.get("Repository")
    if repository and isinstance(repository, list):
        code["Repository"] = convert_cvs_list_to_str(repository)

    try:
        upstream_metadata = UpstreamMetadata.from_dict(code, "certain")
    except TypeError:
        raise TypeError(f"Invalid upstream metadata: {code!r}")

    minimum_certainty = os.environ.get("MINIMUM_CERTAINTY")
    net_access = net_access_allowed()

    # Downgrade minimum certainty, since check_upstream_metadata can
    # upgrade it to "certain" later.
    initial_minimum_certainty = (
        "likely"
        if net_access and minimum_certainty == "certain"
        else minimum_certainty
    )

    # Do some guessing based on what's in the package
    update_from_guesses(
        upstream_metadata,
        filter_bad_guesses(
            guess_upstream_metadata_items(
                ".",
                trust_package=trust_package(),
                minimum_certainty=initial_minimum_certainty,
            )
        ),
    )

    # Then extend that by contacting e.g. SourceForge
    extend_upstream_metadata(
        upstream_metadata,
        ".",
        minimum_certainty=initial_minimum_certainty,
        net_access=net_access,
        consult_external_directory=True,
    )

    if net_access:
        # Verify that online resources actually exist and adjust certainty
        # accordingly.
        upstream_version = debian_to_upstream_version(current_version)
        check_upstream_metadata(upstream_metadata, version=upstream_version)

    # Homepage is set in debian/control, so don't add it to
    # debian/upstream/metadata.
    external_present_fields = {"Homepage"}

    # If the debian/copyright file is machine-readable, then we do
    # not need to set the Name/Contact information in the
    # debian/upstream/metadata file.
    if "Name" in upstream_metadata or "Contact" in upstream_metadata:
        from debmutate.copyright import upstream_fields_in_copyright

        external_present_fields.update(upstream_fields_in_copyright().keys())

    for key, datum in list(upstream_metadata.items()):
        # Drop keys that don't need to be in debian/upstream/metadata
        if key not in DEP12_FIELDS or key in external_present_fields:
            del upstream_metadata[key]

        # Drop everything that is below our minimum certainty
        elif not meets_minimum_certainty(datum.certainty):
            del upstream_metadata[key]

    achieved_certainty = min_certainty(
        [d.certainty for d in upstream_metadata.values()]
    )

    fix_upstream_metadata(upstream_metadata)

    changed = {
        k: v
        for k, v in upstream_metadata.items()
        if v.value != editor.code.get(k)
    }

    if not changed:
        sys.exit(0)

    filter_by_tag(
        editor.code,
        changed,
        ["Repository", "Repository-Browse"],
        "upstream-metadata-missing-repository",
    )

    filter_by_tag(
        editor.code,
        changed,
        ["Bug-Database", "Bug-Submit"],
        "upstream-metadata-missing-bug-tracking",
    )

    # A change that just says the "Name" field is a bit silly
    if set(changed.keys()) - set(ADDON_ONLY_FIELDS) == {"Name"}:
        sys.exit(0)

    if not os.path.exists("debian/upstream/metadata"):
        missing_file_issue.report_fixed()

    update_ordered_dict(
        editor.code,
        [(k, v.value) for (k, v) in changed.items()],
        key=upstream_metadata_sort_key,
    )

    # If there are only add-on-only fields, then just remove the file.
    if not (set(editor.code.keys()) - set(ADDON_ONLY_FIELDS)):
        editor.code.clear()

    if editor.code and not os.path.isdir("debian/upstream"):
        os.makedirs("debian/upstream", exist_ok=True)


# TODO(jelmer): Add note about other origin fields?
fields = [
    (f"{v.field} (from {v.origin})") if v.origin == "./configure" else v.field
    for k, v in sorted(changed.items())
]

report_result(
    "Set upstream metadata fields: {}.".format(", ".join(sorted(fields))),
    certainty=achieved_certainty,
)
