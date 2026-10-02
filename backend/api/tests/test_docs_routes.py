"""
Guard against API docs drifting from the URL configuration (issue #201).

Every routed endpoint must appear in docs/api/API-Reference.md. The unversioned
``/api/`` alias is only checked for routes that aren't also mounted under ``/api/v1/``.
"""
import re
from pathlib import Path

import pytest
from django.urls import URLResolver, get_resolver

API_REFERENCE = Path(__file__).resolve().parents[3] / 'docs' / 'api' / 'API-Reference.md'

_PARAM = re.compile(r'\(\?P<[^>]+>[^)]*\)|<[^>]+>|\{[^}]+\}')
# Routes that are not endpoints in their own right.
_IGNORED = {'/api/', '/api/v1/'}


def _normalize(path: str) -> str:
    path = path.replace('^', '').replace('$', '')
    path = _PARAM.sub('{}', path)
    return '/' + path.lstrip('/')


def _routed_paths():
    def walk(patterns, prefix=''):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, prefix + str(pattern.pattern))
            else:
                yield prefix + str(pattern.pattern)

    paths = set()
    for raw in walk(get_resolver().url_patterns):
        if 'format' in raw or raw.startswith('django-admin/'):
            continue  # DRF format-suffix variants and the Django admin
        paths.add(_normalize(raw))
    v1 = {p for p in paths if p.startswith('/api/v1/')}
    aliased = {'/api/' + p[len('/api/v1/'):] for p in v1}
    return {p for p in paths if p not in aliased} - _IGNORED


def _documented_paths():
    text = API_REFERENCE.read_text()
    found = re.findall(r'(/(?:api|internal|health)[A-Za-z0-9_\-/{}.]*)', text)
    return {_normalize(p.split('?')[0]) for p in found}


@pytest.mark.skipif(not API_REFERENCE.exists(), reason='docs/ not available in this checkout')
def test_every_routed_endpoint_is_documented():
    missing = sorted(_routed_paths() - _documented_paths())
    assert not missing, f'Routes missing from docs/api/API-Reference.md: {missing}'
