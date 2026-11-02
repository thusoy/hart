import base64
import contextlib
import hashlib
import time
import select
import socket

import paramiko
from paramiko.ssh_exception import SSHException

from .utils import log_error


class IgnorePolicy(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        # In paramiko prior to 3.0.0 key.__str__() returned bytes and there was no __bytes__
        key_digest = hashlib.sha256(
            key.__bytes__() if hasattr(key, "__bytes__") else key.__str__()
        ).digest()
        fingerprint = "SHA256:%s" % base64.b64encode(key_digest).decode("utf-8")
        print(
            "Accepting host key type %s with fingerprint %s"
            % (key.get_name(), fingerprint)
        )


def ssh_run_command(client, command, timeout=3, log_stdout=True):
    captured_stdout = []
    session = client.get_transport().open_session()
    session.exec_command(command)
    chunksize = 1024
    start_time = time.time()
    while True:
        (reads_ready, _, _) = select.select([session], [], [], 1)
        if timeout and time.time() - start_time > timeout:
            raise ValueError('Timed out waiting for command %r to finish' % command)

        if not reads_ready:
            continue

        got_data = False
        if session.recv_ready():
            chunk = reads_ready[0].recv(chunksize).decode('utf-8')
            if chunk:
                got_data = True
                captured_stdout.append(chunk)
                if log_stdout:
                    print(chunk, end='')

        if session.recv_stderr_ready():
            chunk = reads_ready[0].recv_stderr(chunksize).decode('utf-8')
            if chunk:
                got_data = True
                log_error(chunk, end='')

        if not got_data:
            break

    while not session.exit_status_ready():
        if timeout and time.time() - start_time > timeout:
            raise ValueError('Timed out waiting for command %r to return an exit code' % command)
        time.sleep(1)

    exit_status = session.recv_exit_status()
    if exit_status != 0:
        raise ValueError('Command %r failed with exit code %d' % (command, exit_status))

    return ''.join(captured_stdout)


def ssh_run_init_script(client, local_script_path):
    sftp_client = client.open_sftp()
    # Preserving this on disk as a record of how the node was created
    remote_script_path = '/root/hart-init'
    with sftp_client.file(remote_script_path, 'wx') as remote_file:
        with open(local_script_path, 'rb') as local_file:
            chunk_size = 16*2**10
            for chunk in iter(lambda: local_file.read(chunk_size), b''):
                remote_file.write(chunk)
    sftp_client.chmod(remote_script_path, 0o700)
    sftp_client.close()
    print('Running custom init script')
    ssh_run_command(client, remote_script_path, timeout=None)


@contextlib.contextmanager
def get_verified_ssh_client(ip, ssh_key, canary, username='root'):
    client = connect_to_node(ip, ssh_key, username)
    print('Connected')

    # Verify the ssh canary as the first thing to not run any potentially
    # dangerous operations on an untrusted box
    client = run_while_booting(client,
        lambda client: wait_for_verified_ssh_canary(client, canary,
            should_sudo=username != 'root'),
        ip, ssh_key, username)
    print('Verified connection')
    try:
        yield client
    except:
        client.close()
        raise


def log_action(action, start_time):
    print('action=%s time=%.2fs' % (action, time.time() - start_time))


def connect_to_node(ip, client_ssh_key, username):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(IgnorePolicy())
    timeout = 120
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            client.connect(ip, username=username, pkey=client_ssh_key, timeout=3)
            log_action('connect', start_time)
            break
        except (socket.error, SSHException) as error:
            print('Could not connect yet, waiting (%s)' % error)
            time.sleep(2)
    else:
        raise ValueError('Failed to connect to new node')

    return client


def run_while_booting(client, action, ip, ssh_key, username, timeout=60):
    '''Run action(client) on a node that is still booting, where sshd can be
    slow to open a session or get reloaded by cloud-init right after we
    connected. Returns the client the action succeeded with, which is a new
    one if the connection had to be re-established.'''
    start_time = time.time()
    while True:
        try:
            action(client)
            return client
        except SSHException as error:
            if time.time() - start_time > timeout:
                raise
            print('Could not run command yet, waiting (%s)' % error)
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                client = connect_to_node(ip, ssh_key, username)
            time.sleep(2)


def wait_for_verified_ssh_canary(client, ssh_canary, should_sudo):
    timeout = 60
    start_time = time.time()
    while time.time() - start_time < timeout:
        # The remove is just a matter of cleanup, the canary isn't sensitive
        _, stdout, stderr = client.exec_command(
            'cat /tmp/ssh-canary && {0}rm /tmp/ssh-canary'.format('sudo ' if should_sudo else ''),
            timeout=3)
        if stderr.channel.recv_exit_status() != 0:
            print('No ssh canary yet, waiting (%s)' % ''.join(stderr).strip())
            time.sleep(1)
            continue

        found_canary = ''.join(stdout).strip()
        if found_canary != ssh_canary:
            raise ValueError('ssh canary check failed!')

        log_action('canary-check', start_time)
        break
    else:
        raise ValueError('No canary found before timeout')
