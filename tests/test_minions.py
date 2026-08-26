import contextlib
from unittest import mock

import pytest

from hart.exceptions import UserError
from hart.minions import connect_minion, create_node
from hart.utils import HartNode


def build_mock_provider(public_ip='203.0.113.5', private_ip='10.0.0.5'):
    provider = mock.Mock()
    provider.username = 'root'

    node = mock.Mock()
    node.public_ips = [public_ip] if public_ip else []
    node.private_ips = [private_ip] if private_ip else []

    @contextlib.contextmanager
    def create_temp_ssh_key(key_name):
        yield ('temp-ssh-key', 'auth-key')

    provider.create_temp_ssh_key = create_temp_ssh_key
    provider.create_node.return_value = (node, None)
    provider.wait_for_public_ip.return_value = node
    return provider


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_connects_via_public_ip_by_default(mock_pubkey, mock_existing):
    provider = build_mock_provider()

    hart_node = create_node('minion.example.com', provider)

    assert hart_node.public_ip == '203.0.113.5'
    assert hart_node.connect_ip == '203.0.113.5'


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_can_connect_via_private_ip(mock_pubkey, mock_existing):
    provider = build_mock_provider()

    hart_node = create_node('minion.example.com', provider,
        connect_via_private_ip=True)

    assert hart_node.public_ip == '203.0.113.5'
    assert hart_node.connect_ip == '10.0.0.5'


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_without_public_ip(mock_pubkey, mock_existing):
    provider = build_mock_provider(public_ip=None)

    hart_node = create_node('minion.example.com', provider, no_public_ip=True)

    assert hart_node.public_ip is None
    assert hart_node.connect_ip == '10.0.0.5'
    # Waiting for an IP the node will never get would just time out
    provider.wait_for_public_ip.assert_not_called()
    assert provider.create_node.call_args[1]['no_public_ip'] is True


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_without_public_ip_needs_a_private_ip(mock_pubkey, mock_existing):
    provider = build_mock_provider(public_ip=None, private_ip=None)

    with pytest.raises(UserError):
        create_node('minion.example.com', provider, no_public_ip=True)

    provider.destroy_node.assert_called_once()


@mock.patch('hart.minions.check_existing_minion', return_value=True)
@mock.patch('hart.minions.get_master_pubkey', return_value='master-pubkey')
def test_create_node_fails_cleanly_without_private_ip(mock_pubkey, mock_existing):
    provider = build_mock_provider(private_ip=None)

    with pytest.raises(UserError):
        create_node('minion.example.com', provider,
            connect_via_private_ip=True)

    provider.destroy_node.assert_called_once()


@mock.patch('hart.minions.verify_minion_connection')
@mock.patch('hart.minions.trust_minion_key')
@mock.patch('hart.minions.get_minion_pubkey', return_value='minion-pubkey')
@mock.patch('hart.minions.get_verified_ssh_client')
def test_connect_minion_uses_connect_ip(
        mock_get_client, mock_minion_pubkey, mock_trust, mock_verify):
    provider = mock.Mock()
    provider.username = 'root'
    hart_node = HartNode('minion.example.com', '203.0.113.5', mock.Mock(),
        provider, 'temp-ssh-key', 'canary', None, '10.0.0.5')

    connect_minion(hart_node, None)

    assert mock_get_client.call_args[0][0] == '10.0.0.5'


@mock.patch('hart.minions.verify_minion_connection')
@mock.patch('hart.minions.trust_minion_key')
@mock.patch('hart.minions.get_minion_pubkey', return_value='minion-pubkey')
@mock.patch('hart.minions.get_verified_ssh_client')
def test_connect_minion_falls_back_to_public_ip(
        mock_get_client, mock_minion_pubkey, mock_trust, mock_verify):
    # HartNodes built without a connect_ip (f.ex by older consumers) should
    # keep connecting to the public IP
    provider = mock.Mock()
    provider.username = 'root'
    hart_node = HartNode('minion.example.com', '203.0.113.5', mock.Mock(),
        provider, 'temp-ssh-key', 'canary', None)

    connect_minion(hart_node, None)

    assert mock_get_client.call_args[0][0] == '203.0.113.5'
