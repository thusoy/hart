import os
import tempfile

import pytest


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
