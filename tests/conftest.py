import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def isolated_minion_store(tmp_path, monkeypatch):
    '''Keep tests from touching the system-wide minion store.'''
    store_path = tmp_path / 'minions.json'
    monkeypatch.setenv('HART_MINION_STORE', str(store_path))
    return store_path


@pytest.fixture
def named_tempfile():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        yield tmp
    finally:
        os.remove(tmp.name)


@pytest.fixture
def local_config():
    return os.path.join(os.path.dirname(__file__), '..', 'hart.toml')
