#!/usr/bin/python3

import argparse
import subprocess
import sys

from ruamel.yaml import YAML

from lintian_brush import available_lintian_fixers

KNOWN_KEYS = ["tag", "status", "difficulty", "comment"]

all_tags = {
    tag.decode()
    for tag in subprocess.check_output(
        ["lintian-explain-tags", "--list-tags"]
    ).splitlines()
}

supported_tags = set()
for fixer in available_lintian_fixers():
    supported_tags.update(fixer.lintian_tags)

yaml = YAML()
with open("tag-status.yaml") as f:
    tag_status = yaml.load(f)

per_tag_status = {}
for entry in tag_status or []:
    per_tag_status[entry["tag"]] = entry
    extra_keys = set(entry.keys()) - set(KNOWN_KEYS)
    assert not extra_keys, "Unknown keys: %r" % extra_keys


for tag in supported_tags:
    existing = per_tag_status.get(tag)
    if existing and existing.get("status") != "implemented":
        raise Exception(
            f"tag {tag} is marked as {existing.get('status')} "
            f"in tag-status.yaml, but implemented"
        )
    per_tag_status[tag] = {"status": "implemented"}


parser = argparse.ArgumentParser()
parser.add_argument(
    "--new-tags", action="store_true", help="List missing tags."
)
parser.add_argument("--check", action="store_true", help="Check tags.")
args = parser.parse_args()

if args.new_tags:
    for tag in sorted(all_tags):
        if tag not in per_tag_status:
            print(tag)
elif args.check:
    retcode = 0
    for tag in sorted(all_tags):
        if tag not in per_tag_status:
            print("Missing tag: %s" % tag)
            retcode = 1
    sys.exit(retcode)
