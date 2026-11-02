import tempfile
from unittest import mock

from hart.master import connect_to_master


HOST_KEYS = (
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHGNtH1zR7IdMg+eTBgUjK7m0RHuD1cQrMZ5B8v5Y5+V root@master\n'
    'ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTY= root@master\n'
)


@mock.patch('hart.master.ssh_run_command')
@mock.patch('hart.master.get_verified_ssh_client')
def test_connecting_writes_a_known_hosts_file_for_the_new_master(
        mock_get_client, mock_run_command, capsys, tmp_path, monkeypatch):
    # tempfile caches the temp dir on first use, so TMPDIR is too late here
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    mock_get_client.return_value.__enter__.return_value = mock.Mock()
    mock_run_command.return_value = HOST_KEYS
    hart_node = mock.Mock(connect_ip='203.0.113.5', public_ip='203.0.113.5')
    hart_node.provider.username = 'root'

    connect_to_master(hart_node, script=None)

    output = capsys.readouterr().out
    known_hosts = next(tmp_path.glob('hart-*/known_hosts'))
    assert known_hosts.read_text() == (
        '203.0.113.5 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHGNtH1zR7IdMg+eTBgUjK7m0RHuD1cQrMZ5B8v5Y5+V\n'
        '203.0.113.5 ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTY=\n'
    )
    assert oct(known_hosts.stat().st_mode & 0o777) == '0o600'
    # The command trusts the keys for this session without touching ~/.ssh
    assert 'ssh -o UserKnownHostsFile=%s root@203.0.113.5' % known_hosts in output
    # Fingerprints are derived locally from the same keys, as ssh-keygen -l
    # would print them, so the keys are only fetched once
    assert 'ssh-ed25519 SHA256:B970hxKQtq+8OucXyrRye3rPzfyEusTnKGp1XPIKVD8' in output
    assert 'ecdsa-sha2-nistp256 SHA256:hbXWYdBrsOyu43/M0JizUP5K25IjKV8Zs5EZtJ9O6XI' in output
    assert mock_run_command.call_count == 1
