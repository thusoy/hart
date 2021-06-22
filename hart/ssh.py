import base64
import contextlib
import hashlib
import os
import time
import select
import socket

import paramiko
from paramiko.ssh_exception import SSHException

from .utils import log_error


class IgnorePolicy(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        # key.__str__() isn't valid according to str() since it returns bytes, thus
        # calling it directly
        key_digest = hashlib.sha256(key.__str__()).digest()
        fingerprint = 'SHA256:%s' % base64.b64encode(key_digest).decode('utf-8')
        print('Accepting host key type %s with fingerprint %s' % (
            key.get_name(), fingerprint))


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


@contextlib.contextmanager
def get_verified_ssh_client(ip, ssh_key, canary, username='root'):
    client = connect_to_droplet(ip, ssh_key, username)
    print('Connected')

    # We might not be connected to the right box yet, but we should help seed
    # the random pool as early as possible in the boot sequence. There's nothing
    # sensitive here as we'll disconnect if the canary fails in the next step
    # and the minion will be destroyed. Doing this in addition to seeding over
    # cloud-init since the contents of cloud-init is rarely safe from someone
    # that manages to compromise the server.
    print('Seeding random pool')
    seed_client_random_pool(client)

    # Verify the ssh canary as the first thing to not run any potentially
    # dangerous operations on an untrusted box
    wait_for_verified_ssh_canary(client, canary, should_sudo=username != 'root')
    print('Verified connection')
    try:
        yield client
    except:
        client.close()
        raise


def log_action(action, start_time):
    print('action=%s time=%.2fs' % (action, time.time() - start_time))


def connect_to_droplet(ip, client_ssh_key, username):
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


def seed_client_random_pool(client):
    seed = os.urandom(32)
    stdin, _, _ = client.exec_command('dd of=/dev/random', timeout=3)
    stdin.write(seed)
    stdin.channel.close()


def wait_for_verified_ssh_canary(client, ssh_canary, should_sudo):
    timeout = 15
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
