#!/usr/bin/env python3
"""Refuses a commit that would publish something that should stay local.

Scans a working copy for credentials, machine-specific paths and personal addresses, prints every
hit as path:line, and exits non-zero if anything is found. Run it before every commit:

    python3 scripts/scrub_check.py <repo path>

It is deliberately noisy rather than clever: a false positive costs a glance, a missed token costs
a rotation. Add a genuine false positive to ALLOW below, with a reason.
"""
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'

RULES = [
    ('GitHub token',      re.compile(r'gh[pousr]_[A-Za-z0-9]{16,}')),
    ('GitHub fine-grained token', re.compile(r'github_pat_[A-Za-z0-9_]{20,}')),
    ('generic bearer',    re.compile(r'(?i)\b(authorization|bearer)\s*[:=]\s*\S{12,}')),
    ('HEC / UUID token',  re.compile(r'(?i)\btoken\b\s*[:=]\s*[0-9a-f]{8}-[0-9a-f]{4}-'
                                    r'[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')),
    ('password',          re.compile(r'(?i)\bpassw(or)?d\s*[:=]\s*\S+')),
    ('private key',       re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('local home path',   re.compile(r'/home/[a-z0-9_]{2,}/')),
    ('Windows user path', re.compile(r'(?i)[A-Z]:\\\\?Users\\\\?|/mnt/[a-z]/Users/')),
    ('machine name',      re.compile(r'DESKTOP-[A-Z0-9]{7}')),
    ('personal e-mail',   re.compile(r'[A-Za-z0-9._%+-]+@(?!univaq\.it|graduate\.univaq\.it)'
                                     r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}')),
]

# path fragment -> rule name it may legitimately contain, with the reason
ALLOW = [
    ('README.md',      'local home path',   'the reproduction instructions show example paths'),
    ('CHANGELOG.md',   'local home path',   'same'),
    ('scrub_check.py', None,                'this file contains the patterns themselves'),
]

SKIP_DIRS = {'.git', '__pycache__', '.vscode', '.idea', 'node_modules'}
BINARY_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.gz', '.zip', '.so', '.o', '.pyc', '.ttf'}


def allowed(rel, rule):
    for frag, r, _ in ALLOW:
        if frag in rel and (r is None or r == rule):
            return True
    return False


def main():
    hits = 0
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, ROOT)
            if os.path.splitext(fn)[1].lower() in BINARY_EXT:
                continue
            try:
                with open(p, 'r', errors='replace') as f:
                    lines = f.readlines()
            except OSError:
                continue
            scanned += 1
            for i, line in enumerate(lines, 1):
                if len(line) > 4000:
                    line = line[:4000]
                for name, rx in RULES:
                    if rx.search(line) and not allowed(rel, name):
                        hits += 1
                        print('%s:%d: %s' % (rel, i, name))
                        print('    %s' % line.strip()[:160])
    print()
    print('scanned %d text files' % scanned)
    if hits:
        print('FAIL: %d finding(s). Fix them, or add a justified entry to ALLOW.' % hits)
        return 1
    print('PASS: nothing to scrub.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
