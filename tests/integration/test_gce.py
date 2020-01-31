import pytest

from hart.__main__ import main

pytestmark = pytest.mark.integration


def test_list_regions(local_config, capsys):
    main(['-P', 'gce', '-c', local_config, 'list-regions'])
    captured = capsys.readouterr()
    assert 'Hamina, Finland (europe-north1)' in captured.out
    assert captured.err == ''


def test_list_zones(local_config, capsys):
    main(['-P', 'gce', '-c', local_config, 'list-regions', '--include-zones'])
    captured = capsys.readouterr()
    assert 'Hamina, Finland (europe-north1-a)' in captured.out
    assert captured.err == ''
