import datetime
import json
import os
from unittest import mock

import pytest

from hart import minion_store
from hart.__main__ import HartCLI
from hart.exceptions import UserError
from hart.minions import create_node, destroy_minion, destroy_node
from hart.providers import DOProvider
from hart.utils import HartNode

from test_minions import build_mock_provider


def build_record(minion_id='minion.example.com', provider='do', **overrides):
    node = mock.Mock()
    node.id = 'node-123'
    node.name = minion_id
    node.public_ips = ['203.0.113.5']
    node.private_ips = ['10.0.0.5']
    record = minion_store.build_record(minion_id, provider, node,
        region='ams3', zone=None, size='s-1vcpu-1gb', debian_codename='bookworm',
        roles=['web'])
    record.update(overrides)
    return record


def test_add_get_list_remove_roundtrip():
    record = build_record()
    minion_store.add_minion(record)

    assert minion_store.get_minion('minion.example.com') == record
    assert minion_store.list_minions() == [record]

    removed = minion_store.remove_minion('minion.example.com')
    assert removed == record
    assert minion_store.get_minion('minion.example.com') is None
    assert minion_store.list_minions() == []


def test_add_overwrites_existing_record():
    minion_store.add_minion(build_record(size='s-1vcpu-1gb'))
    minion_store.add_minion(build_record(size='s-2vcpu-2gb'))

    minions = minion_store.list_minions()
    assert len(minions) == 1
    assert minions[0]['size'] == 's-2vcpu-2gb'


def test_list_minions_is_sorted_by_minion_id():
    minion_store.add_minion(build_record('b.example.com'))
    minion_store.add_minion(build_record('a.example.com'))

    assert [m['minion_id'] for m in minion_store.list_minions()] == [
        'a.example.com', 'b.example.com']


def test_remove_missing_minion_returns_none(isolated_minion_store):
    assert minion_store.remove_minion('unknown.example.com') is None
    # Nothing was changed, so no store should have been written either
    assert not os.path.exists(isolated_minion_store)


def test_store_is_plain_versioned_json(isolated_minion_store):
    # Other tools (like custom salt modules) read the store directly, keep the
    # format a stable contract
    minion_store.add_minion(build_record())

    with open(isolated_minion_store) as fh:
        store = json.load(fh)

    assert store['version'] == 1
    record = store['minions']['minion.example.com']
    assert record['provider'] == 'do'
    assert record['region'] == 'ams3'
    assert record['public_ips'] == ['203.0.113.5']
    assert record['private_ips'] == ['10.0.0.5']
    assert record['node_id'] == 'node-123'
    assert record['node_name'] == 'minion.example.com'
    assert record['debian_codename'] == 'bookworm'
    assert record['roles'] == ['web']


def test_explicit_path_overrides_default(tmp_path):
    path = str(tmp_path / 'other-store.json')
    minion_store.add_minion(build_record(), path=path)

    assert minion_store.get_minion('minion.example.com', path=path) is not None
    assert minion_store.get_minion('minion.example.com') is None


def test_build_record_keeps_provided_creation_time():
    node = mock.Mock()
    node.id = 'node-123'
    node.name = 'minion.example.com'
    node.public_ips = ['203.0.113.5']
    node.private_ips = []
    created_at = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=datetime.timezone.utc)

    record = minion_store.build_record('minion.example.com', 'do', node,
        created_at=created_at)

    assert record['created_at'] == '2026-08-06T12:00:00+00:00'
    assert record['roles'] == []


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_saves_minion_to_store(mock_pubkey, mock_existing):
    provider = build_mock_provider()
    provider.alias = 'do'
    provider.default_size = 's-1vcpu-1gb'
    node = provider.create_node.return_value[0]
    node.id = 'droplet-123'
    node.name = 'minion.example.com'

    create_node('minion.example.com', provider, region='ams3',
        debian_codename='bookworm', minion_config={'grains': {'roles': ['web']}})

    record = minion_store.get_minion('minion.example.com')
    assert record['provider'] == 'do'
    assert record['region'] == 'ams3'
    assert record['size'] == 's-1vcpu-1gb'
    assert record['debian_codename'] == 'bookworm'
    assert record['roles'] == ['web']
    assert record['public_ips'] == ['203.0.113.5']
    assert record['private_ips'] == ['10.0.0.5']
    assert record['node_id'] == 'droplet-123'
    assert record['node_name'] == 'minion.example.com'


@mock.patch('hart.minions.disconnect_minion')
def test_destroy_minion_removes_minion_from_store(mock_disconnect):
    minion_store.add_minion(build_record())
    provider = mock.Mock()

    destroy_minion('minion.example.com', provider)

    provider.destroy_node.assert_called_once()
    assert minion_store.get_minion('minion.example.com') is None


def test_destroy_node_removes_minion_from_store():
    minion_store.add_minion(build_record())
    provider = mock.Mock()
    hart_node = HartNode('minion.example.com', '203.0.113.5', mock.Mock(),
        provider, 'temp-ssh-key', 'canary', None)

    destroy_node(hart_node)

    provider.destroy_node.assert_called_once()
    assert minion_store.get_minion('minion.example.com') is None


def build_config(tmp_path):
    config_path = tmp_path / 'hart.toml'
    config_path.write_text('[providers.do]\ntoken = "test-token"\n')
    return str(config_path)


def test_destroy_minion_resolves_provider_from_store(tmp_path):
    minion_store.add_minion(build_record())
    cli = HartCLI()

    args = cli.get_args(['-c', build_config(tmp_path),
        'destroy-minion', 'minion.example.com'])

    assert isinstance(args.provider, DOProvider)


def test_destroy_minion_without_provider_or_store_record_errors(tmp_path):
    cli = HartCLI()

    with pytest.raises(UserError) as error:
        cli.get_args(['-c', build_config(tmp_path),
            'destroy-minion', 'unknown.example.com'])

    assert 'not found in the local minion store' in str(error.value)


def test_list_minions_needs_no_provider(capsys):
    minion_store.add_minion(build_record())
    cli = HartCLI()

    args = cli.get_args(['list-minions'])
    assert args.provider is None

    args.action(args)
    output = capsys.readouterr().out
    assert 'minion.example.com' in output
    assert '203.0.113.5' in output


def test_list_minions_as_json(capsys):
    minion_store.add_minion(build_record())
    cli = HartCLI()

    args = cli.get_args(['list-minions', '--json'])
    args.action(args)

    minions = json.loads(capsys.readouterr().out)
    assert minions[0]['minion_id'] == 'minion.example.com'


def test_import_minion_adds_node_to_store():
    provider = mock.Mock()
    provider.alias = 'do'
    node = mock.Mock()
    node.id = 'droplet-123'
    node.name = 'minion.example.com'
    node.public_ips = ['203.0.113.5']
    node.private_ips = []
    node.created_at = None
    provider.get_node.return_value = node
    args = mock.Mock()
    args.minion_id = 'minion.example.com'
    args.provider = provider
    args.region = 'ams3'
    args.zone = None
    args.debian_codename = 'bookworm'
    args.roles = ['web']

    HartCLI().cli_import_minion(args)

    record = minion_store.get_minion('minion.example.com')
    assert record['provider'] == 'do'
    assert record['region'] == 'ams3'
    assert record['roles'] == ['web']
    assert record['node_id'] == 'droplet-123'
    assert record['debian_codename'] == 'bookworm'
