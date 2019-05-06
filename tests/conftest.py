import os
import tempfile

import pytest


@pytest.yield_fixture
def named_tempfile():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        yield tmp
    finally:
        os.remove(tmp.name)
