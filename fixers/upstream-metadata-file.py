#!/usr/bin/python3

# TODO(jelmer): Read python3 setup.py dist_info
# TODO(jelmer): Check XS-Go-Import-Path

import os
import sys
from lintian_brush import (
    min_certainty,
    )
from lintian_brush.fixer import (
    current_package_version,
    package_is_native,
    meets_minimum_certainty,
    net_access_allowed,
    override_exists,
    report_result,
    trust_package,
    fixed_lintian_tag,
    )
from lintian_brush.upstream_metadata import (
    UpstreamDatum,
    check_upstream_metadata,
    extend_upstream_metadata,
    fix_upstream_metadata,
    guess_upstream_metadata_items,
    update_from_guesses,
    filter_bad_guesses,
    ADDON_ONLY_FIELDS,
    upstream_metadata_sort_key,
    upstream_version,
    )
from lintian_brush.yaml import (
    YamlUpdater,
    update_ordered_dict,
    )


def filter_by_tag(orig, changed, fields, tag):
    if all(field in orig for field in fields):
        return

    if (not all(field in orig for field in fields) and
            override_exists('source', tag)):
        for field in fields:
            if field in changed:
                del changed[field]

    if all(field in orig or field in changed for field in fields):
        fixed_lintian_tag('source', tag)


if package_is_native():
    # Native package
    sys.exit(0)


current_version = current_package_version()

if not os.path.exists('debian/upstream/metadata') and override_exists(
        'source', tag='upstream-metadata-file-is-missing'):
    sys.exit(0)


with YamlUpdater('debian/upstream/metadata') as editor:
    if isinstance(editor.code, str):
        sys.exit(0)

    upstream_metadata = {
        k: UpstreamDatum(k, v, 'certain') for (k, v) in editor.code.items()}

    minimum_certainty = os.environ.get('MINIMUM_CERTAINTY')
    net_access = net_access_allowed()

    # Do some guessing based on what's in the package
    update_from_guesses(
        upstream_metadata, filter_bad_guesses(
            guess_upstream_metadata_items(
                '.', trust_package=trust_package())))

    # Then extend that by contacting e.g. SourceForge
    extend_upstream_metadata(
        upstream_metadata, '.',
        # Downgrade minimum certainty, since check_upstream_metadata can
        # upgrade it to "certain" later.
        minimum_certainty=(
            'likely'
            if net_access and minimum_certainty == 'certain'
            else minimum_certainty),
        net_access=net_access,
        consult_external_directory=True)
    if net_access:
        # Verify that online resources actually exist and adjust certainty
        # accordingly.
        upstream_version = upstream_version(current_version)
        check_upstream_metadata(upstream_metadata, version=upstream_version)

    # Homepage is set in debian/control, so don't add it to
    # debian/upstream/metadata.
    external_present_fields = set(['Homepage'])

    # If the debian/copyright file is machine-readable, then we do
    # not need to set the Name/Contact information in the
    # debian/upstream/metadata file.
    if 'Name' in upstream_metadata or 'Contact' in upstream_metadata:
        from debmutate.copyright import upstream_fields_in_copyright
        external_present_fields.update(upstream_fields_in_copyright().keys())

    for key, datum in list(upstream_metadata.items()):
        # Drop keys that don't need to be in debian/upsteam/metadata
        if key.startswith('X-') or key in external_present_fields:
            del upstream_metadata[key]

        # Drop everything that is below our minimum certainty
        elif not meets_minimum_certainty(datum.certainty):
            del upstream_metadata[key]

    achieved_certainty = min_certainty(
        [d.certainty for d in upstream_metadata.values()])

    fix_upstream_metadata(upstream_metadata)

    changed = {
        k: v
        for k, v in upstream_metadata.items()
        if v.value != editor.code.get(k)}

    if not changed:
        sys.exit(0)

    filter_by_tag(
        editor.code, changed,
        ['Repository', 'Repository-Browse'],
        'upstream-metadata-missing-repository')

    filter_by_tag(
        editor.code, changed,
        ['Bug-Database', 'Bug-Submit'],
        'upstream-metadata-missing-bug-tracking')

    # A change that just says the "Name" field is a bit silly
    if set(changed.keys()) - set(ADDON_ONLY_FIELDS) == set(['Name']):
        sys.exit(0)

    if not os.path.exists('debian/upstream/metadata'):
        fixed_lintian_tag('source', 'upstream-metadata-file-is-missing')

    update_ordered_dict(
        editor.code, [(k, v.value) for (k, v) in changed.items()],
        key=upstream_metadata_sort_key)

    # If there are only add-on-only fields, then just remove the file.
    if not (set(editor.code.keys()) - set(ADDON_ONLY_FIELDS)):
        editor.code.clear()

    if editor.code and not os.path.isdir('debian/upstream'):
        os.makedirs('debian/upstream', exist_ok=True)


fields = [
    ('%s (from %s)' % (v.field, v.origin)) if v.origin else v.field
    for k, v in sorted(changed.items())
    ]

report_result(
    'Set upstream metadata fields: %s.' % ', '.join(sorted(fields)),
    certainty=achieved_certainty)
