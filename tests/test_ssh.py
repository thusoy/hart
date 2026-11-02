from unittest import mock

from paramiko.ssh_exception import SSHException
import pytest

from hart import ssh


def build_client(active=True):
    client = mock.Mock()
    client.get_transport.return_value.is_active.return_value = active
    return client


def run_command(client):
    client.exec_command('cat /tmp/ssh-canary', timeout=3)


@mock.patch('hart.ssh.time.sleep')
def test_retries_session_open_while_node_is_booting(mock_sleep):
    client = build_client()
    client.exec_command.side_effect = [
        SSHException('Timeout opening channel.'),
        SSHException('Timeout opening channel.'),
        (mock.Mock(), mock.Mock(), mock.Mock()),
    ]

    ret = ssh.run_while_booting(client, run_command, '203.0.113.5', 'key', 'root')

    assert ret is client
    assert client.exec_command.call_count == 3


@mock.patch('hart.ssh.time.sleep')
@mock.patch('hart.ssh.connect_to_node')
def test_reconnects_when_the_connection_dropped(mock_connect, mock_sleep):
    dead_client = build_client(active=False)
    dead_client.exec_command.side_effect = SSHException('SSH session not active')
    new_client = build_client()
    new_client.exec_command.return_value = (mock.Mock(), mock.Mock(), mock.Mock())
    mock_connect.return_value = new_client

    ret = ssh.run_while_booting(dead_client, run_command, '203.0.113.5', 'key', 'root')

    assert ret is new_client
    mock_connect.assert_called_once_with('203.0.113.5', 'key', 'root')


@mock.patch('hart.ssh.time.sleep')
@mock.patch('hart.ssh.time.time', side_effect=[0, 0, 100, 100])
def test_gives_up_after_the_timeout(mock_time, mock_sleep):
    client = build_client()
    client.exec_command.side_effect = SSHException('Timeout opening channel.')

    with pytest.raises(SSHException):
        ssh.run_while_booting(client, run_command, '203.0.113.5', 'key', 'root',
            timeout=60)
