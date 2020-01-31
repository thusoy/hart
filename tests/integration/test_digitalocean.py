import pytest

from hart.__main__ import main

pytestmark = pytest.mark.integration


def test_list_regions(local_config, capsys):
    main(['-P', 'do', '-c', local_config, 'list-regions'])
    captured = capsys.readouterr()
    assert 'New York 1 (nyc1)' in captured.out
    assert captured.err == ''
