import pytest

from hart.__main__ import main

pytestmark = pytest.mark.integration


def test_list_regions(local_config, capsys):
    main(['-P', 'ec2', '-c', local_config, 'list-regions'])
    captured = capsys.readouterr()
    assert 'EU (Ireland) (eu-west-1)' in captured.out
    assert captured.err == ''


def test_list_zones(local_config, capsys):
    main(['-P', 'ec2', '-c', local_config, 'list-regions', '--include-zones'])
    captured = capsys.readouterr()
    assert 'EU (Ireland) (eu-west-1a)' in captured.out
    assert captured.err == ''


def test_list_sizes_without_region(local_config, capsys):
    main(['-P', 'ec2', '-c', local_config, 'list-sizes'])
    captured = capsys.readouterr()
    assert captured.out.count('2 vCPUs, 8 GB RAM, EBS only (m4.large, $72/month)') == 1
    assert captured.err == ('No region specified, using us-east-1. Sizes listed might not exist '
                'in any other region\n')


def test_list_sizes(local_config, capsys):
    main(['-P', 'ec2', '-R', 'us-west-1', '-c', local_config, 'list-sizes'])
    captured = capsys.readouterr()
    assert captured.out.count('2 vCPUs, 8 GB RAM, EBS only (m4.large, $84/month)') == 1
    assert captured.err == ''
