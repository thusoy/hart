import tempfile
import textwrap

from hart.providers import DOProvider
from hart.config import build_provider_from_config, build_provider_from_file


def test_build_provider_from_file(named_tempfile):
    named_tempfile.write(textwrap.dedent('''
        [providers.do]
        token = "foo"
    ''').encode('utf-8'))
    named_tempfile.close()

    provider = build_provider_from_file('do', named_tempfile.name)
    assert isinstance(provider, DOProvider)


def test_build_provider_from_config():
    provider = build_provider_from_config('do', {
        'providers': {
            'do': {'token': 'foo'},
        },
    })
    assert isinstance(provider, DOProvider)
