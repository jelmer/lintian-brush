#!/usr/bin/python3

import os
import subprocess
import shlex
import sys
from typing import List, Optional

gpg = shlex.split(os.environ.get('GPG', 'gpg'))


KEY_BLOCK_START = b'-----BEGIN PGP PUBLIC KEY BLOCK-----'
KEY_BLOCK_END = b'-----END PGP PUBLIC KEY BLOCK-----'


def gpg_import_export(options, stdin):
    argv = gpg + [
            '--armor', '--quiet', '--no-default-keyring',
            '--import-options', ','.join(['import-export'] + options)]
    try:
        p = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    except FileNotFoundError:
        # No gpg, no dice.
        sys.exit(2)
    (stdout, stderr) = p.communicate(stdin, timeout=5)
    if p.returncode != 0:
        raise Exception('gpg failed')
    return stdout


def minimize_key_block(key):
    minimal = gpg_import_export(
        ['import-minimal', 'import-clean', 'self-sigs-only'], key)
    full = gpg_import_export([], key)
    if minimal == full:
        return key
    else:
        return minimal


for p in [
        'debian/upstream/signing-key.asc',
        'debian/upstream/signing-key.pgp',
        'debian/upstream-signing-key.pgp']:
    if os.path.exists(p):
        out: List[bytes] = []
        key: Optional[List[bytes]] = None
        with open(p, 'rb') as f:
            for line in f:
                if line.strip() == KEY_BLOCK_START:
                    key = [line]
                elif line.strip() == KEY_BLOCK_END and key is not None:
                    key.append(line)
                    out.extend(minimize_key_block(
                        b''.join(key)).splitlines(True))
                    key = None
                elif key is not None:
                    key.append(line)
                else:
                    out.append(line)
            if key:
                raise Exception('Key block without end')
        with open(p, 'wb') as f:
            f.writelines(out)


print("Re-export upstream signing key without extra signatures.")
print("Fixed-Lintian-Tags: public-upstream-key-not-minimal")
