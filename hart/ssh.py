import base64
import contextlib
import hashlib
import time
import sys

import paramiko


class IgnorePolicy(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        # key.__str__() isn't valid according to str() since it returns bytes, thus calling it directly
        fingerprint = 'SHA256:%s' % base64.b64encode(hashlib.sha256(key.__str__()).digest()).decode('utf-8')
        print('Accepting host key type %s with fingerprint %s' % (key.get_name(), fingerprint))


def ssh_run_command(client, command, timeout=3, sensitive=False):
    captured_stdout = []
    captured_stderr = []
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    # while not stdout.channel.exit_status_ready():
    # This causes stderr to be depleted before doing anything else, for true interactive output
    # we need to use the channel API directly and use recv_stderr_ready/recv_
    for chunk in stderr:
        captured_stderr.append(chunk)
        end = '' if chunk[-1] == '\n' else '\n'
        sys.stderr.write('stderr: %s%s' % (chunk, end))
    for chunk in stdout:
        captured_stdout.append(chunk)
        end = '' if chunk[-1] == '\n' else '\n'
        print('stdout: %s' % chunk, end=end)

    if stdout.channel.recv_exit_status() != 0:
        if sensitive:
            raise ValueError('Sensitive command failed with exit code %d' % stdout.channel.recv_exit_status())
        raise ValueError('Command %s failed with exit code %d' % (command, stdout.channel.recv_exit_status()))

    return ''.join(captured_stdout)


@contextlib.contextmanager
def get_verified_ssh_client(ip, ssh_key, canary, username='root'):
    client = connect_to_droplet(ip, ssh_key, username)
    print('Connected')

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
    timeout = 90
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            client.connect(ip, username=username, pkey=client_ssh_key, timeout=3)
            log_action('connect', start_time)
            break
        except Exception as e:
            print('Could not connect yet, waiting (%s)' % e)
            time.sleep(2)
    else:
        raise ValueError('Failed to connect to new node')

    return client


def wait_for_verified_ssh_canary(client, ssh_canary, should_sudo):
    timeout = 15
    start_time = time.time()
    while time.time() - start_time < timeout:
        # The remove is just a matter of cleanup, the canary isn't sensitive
        _, stdout, stderr = client.exec_command('cat /tmp/ssh-canary && {0}rm /tmp/ssh-canary'.format('sudo ' if should_sudo else ''), timeout=3)
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
