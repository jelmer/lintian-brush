#!/usr/bin/python3
# Report lintian tags that might be good candidates to implement fixers for.

from lintian_brush import available_lintian_fixers
import psycopg2
from ruamel.yaml import YAML

conn = psycopg2.connect(
    "postgresql://udd-mirror:udd-mirror@udd-mirror.debian.net/udd")
cursor = conn.cursor()
cursor.execute(
    "select tag, count(distinct package) as package_count, "
    "count(*) as tag_count from lintian "
    "where tag_type not in ('classification') group by 1 order by 2 desc")

supported_tags = set()
for fixer in available_lintian_fixers():
    supported_tags.update(fixer.lintian_tags)

yaml = YAML()
with open('tag-status.yaml', 'r') as f:
    tag_status = yaml.load(f)

per_tag_status = {}
for entry in tag_status or []:
    per_tag_status[entry['tag']] = entry


for (tag, package_count, tag_count) in cursor.fetchall():
    if tag in supported_tags:
        continue
    difficulty = per_tag_status.get(tag, {}).get('difficulty', 'unknown')
    print('%s %s %d/%d' % (tag, difficulty, package_count, tag_count))
