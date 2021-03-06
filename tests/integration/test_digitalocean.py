import pytest

from hart.__main__ import main

pytestmark = pytest.mark.integration


def test_list_regions(local_config, capsys):
    main(['-P', 'do', '-c', local_config, 'list-regions'])
    captured = capsys.readouterr()
    assert 'New York 1 (nyc1)' in captured.out
    assert captured.err == ''


def test_list_sizes(local_config, capsys):
    main(['-P', 'do', '-c', local_config, 'list-sizes'])
    captured = capsys.readouterr()
    assert captured.out.count('1 vCPUs, 1 GB RAM, 25 GB SSD (s-1vcpu-1gb, $5/month)') == 1
    assert captured.err == ''
