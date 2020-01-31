import pytest

from hart.__main__ import main

pytestmark = pytest.mark.integration


def test_list_regions(local_config, capsys):
    main(['-P', 'vultr', '-c', local_config, 'list-regions'])
    captured = capsys.readouterr()
    assert 'Los Angeles (5)' in captured.out
    assert captured.err == ''


def test_list_sizes(local_config, capsys):
    main(['-P', 'vultr', '-c', local_config, 'list-sizes'])
    captured = capsys.readouterr()
    assert captured.out.count('1 vCPUs, 2 GB RAM, 55 GB SSD (202, $10/month)') == 1
    assert captured.err == ''
