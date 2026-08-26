from unittest import mock

import pytest

from hart import minion_store
from hart.exceptions import UserError
from hart.minions import create_node
from hart.zones import pick_distributed_zones

from test_minions import build_mock_provider


def build_provider(zones=('zone-a', 'zone-b', 'zone-c'), alias='gce'):
    provider = mock.Mock()
    provider.alias = alias
    provider.get_zones.return_value = list(zones)
    return provider


def add_minion(minion_id, zone, roles=('web',), provider='gce', region='us-east4'):
    node = mock.Mock()
    node.id = 'node-%s' % minion_id
    node.name = minion_id
    node.public_ips = ['203.0.113.5']
    node.private_ips = []
    minion_store.add_minion(minion_store.build_record(
        minion_id, provider, node, region=region, zone=zone, roles=list(roles)))


def test_picks_least_loaded_zone():
    provider = build_provider()
    add_minion('a.example.com', 'zone-a')
    add_minion('b.example.com', 'zone-a')
    add_minion('c.example.com', 'zone-b')

    assert pick_distributed_zones(provider, 'us-east4', ['web']) == ['zone-c']


def test_picks_any_zone_without_existing_minions():
    provider = build_provider()

    assert pick_distributed_zones(provider, 'us-east4', ['web'])[0] in (
        'zone-a', 'zone-b', 'zone-c')


def test_ignores_minions_with_other_roles_regions_and_providers():
    provider = build_provider(zones=('zone-a', 'zone-b'))
    add_minion('other-role.example.com', 'zone-b', roles=('db',))
    add_minion('other-region.example.com', 'zone-b', region='us-west1')
    add_minion('other-provider.example.com', 'zone-b', provider='ec2')
    add_minion('same.example.com', 'zone-a')

    assert pick_distributed_zones(provider, 'us-east4', ['web']) == ['zone-b']


def test_counts_all_minions_when_no_roles_given():
    provider = build_provider(zones=('zone-a', 'zone-b'))
    add_minion('some-role.example.com', 'zone-a', roles=('db',))

    assert pick_distributed_zones(provider, 'us-east4', []) == ['zone-b']


def test_spreads_batches_across_zones():
    provider = build_provider()

    picked = pick_distributed_zones(provider, 'us-east4', ['web'], count=3)

    assert sorted(picked) == ['zone-a', 'zone-b', 'zone-c']


def test_batches_account_for_existing_minions():
    provider = build_provider(zones=('zone-a', 'zone-b'))
    add_minion('a.example.com', 'zone-a')

    picked = pick_distributed_zones(provider, 'us-east4', ['web'], count=3)

    assert sorted(picked) == ['zone-a', 'zone-b', 'zone-b']


def test_no_zones_fails():
    provider = build_provider(zones=())

    with pytest.raises(UserError):
        pick_distributed_zones(provider, 'us-east4', ['web'])


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_resolves_distributed_zone(mock_pubkey, mock_existing):
    provider = build_mock_provider()
    provider.alias = 'gce'
    provider.default_size = 'n1-standard-1'
    provider.get_zones.return_value = ['zone-a', 'zone-b']
    node = provider.create_node.return_value[0]
    node.id = 'instance-123'
    node.name = 'hart-minion-abc123'
    add_minion('existing.example.com', 'zone-a')

    create_node('minion.example.com', provider, region='us-east4',
        zone='distributed', minion_config={'grains': {'roles': ['web']}})

    assert provider.create_node.call_args[1]['zone'] == 'zone-b'
    assert minion_store.get_minion('minion.example.com')['zone'] == 'zone-b'
