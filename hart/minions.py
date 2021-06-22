#!./venv/bin/python

import json
import os
import subprocess
import sys
import time
import traceback

import yaml

from . import utils
from .constants import DEBIAN_VERSIONS
from .ssh import get_verified_ssh_client, ssh_run_command
from .utils import log_error


def create_minion(
        minion_id,
        provider,
        region=None,
        size=None,
        salt_branch='latest',
        debian_codename='stretch',
        tags=None,
        private_networking=False,
        minion_config=None,
        use_py2=False,
        **kwargs
        ):
    hart_node = create_node(
        minion_id,
        provider,
        region,
        size,
        salt_branch,
        debian_codename,
        tags,
        private_networking,
        minion_config,
        use_py2,
        **kwargs
    )
    try:
        connect_minion(hart_node)
    except:
        log_error('Destroying node since it failed to connect')
        hart_node.provider.destroy_node(hart_node.node, extra=hart_node.node_extra)
        disconnect_minion(minion_id)
        raise


def connect_minion(hart_node):
    username = hart_node.provider.username
    with get_verified_ssh_client(
            hart_node.public_ip,
            hart_node.ssh_key,
            hart_node.ssh_canary,
            username) as client:
        hart_node.provider.wait_for_init_script(client, hart_node.node_extra)
        minion_pubkey = get_minion_pubkey(client, should_sudo=username != 'root')
        trust_minion_key(hart_node.minion_id, minion_pubkey)
        print('Minion added: %s' % hart_node.public_ip)
        verify_minion_connection(client, hart_node.minion_id, username)
        hart_node.provider.post_connect(hart_node)


def create_node(
        minion_id,
        provider,
        region=None,
        size=None,
        salt_branch='latest',
        debian_codename='stretch',
        tags=None,
        private_networking=False,
        minion_config=None,
        use_py2=False,
        **kwargs
        ):
    ssh_canary = utils.create_token()
    cloud_init_template = utils.get_cloud_init_template()
    master_pubkey = get_master_pubkey()
    default_minion_config = {
        'id': minion_id,
    }
    if minion_config is not None:
        default_minion_config.update(minion_config)

    saltstack_repo = utils.get_saltstack_repo_url(debian_codename, salt_branch, use_py2)
    cloud_init = cloud_init_template.render(**{
        'random_seed': utils.create_token(),
        'minion_config': yaml.dump(default_minion_config),
        'ssh_canary': ssh_canary,
        'master_pubkey': master_pubkey,
        'saltstack_repo': saltstack_repo,
        'wait_for_apt': DEBIAN_VERSIONS[debian_codename] >= 10,
    })

    key_name = utils.build_ssh_key_name(minion_id)

    if not check_existing_minion(minion_id):
        print('Existing minions were found and did want to overwrite, aborting')
        return

    with provider.create_temp_ssh_key(key_name) as (ssh_key, auth_key):
        node = None
        if size:
            kwargs['size'] = size
        try:
            node, extra = provider.create_node(
                minion_id,
                region,
                debian_codename,
                auth_key,
                cloud_init,
                private_networking,
                tags,
                **kwargs)
            node = provider.wait_for_public_ip(node)
            public_ip = node.public_ips[0]
            print('Node running at %s' % public_ip)
            return utils.HartNode(minion_id, public_ip, node, provider, ssh_key, ssh_canary, extra)
        except:
            traceback.print_exc()
            if node:
                log_error('Destroying node since it failed initialization')
                provider.destroy_node(node, extra)
            raise


def destroy_minion(minion_id, provider, **kwargs):
    disconnect_minion(minion_id)
    print('Destroying minion')
    node = provider.get_node(minion_id)
    provider.destroy_node(node, **kwargs)


def disconnect_minion(minion_id):
    print('Deleting the salt minion %s' % minion_id)
    subprocess.run([
        'salt-key',
        '--delete=%s' % minion_id,
        '--yes',
    ], check=True)


def destroy_node(hart_node):
    hart_node.provider.destroy_node(hart_node.node, extra=hart_node.node_extra)


def get_master_pubkey():
    with open('/etc/salt/pki/master/master.pub') as fh:
        return fh.read()


def check_existing_minion(minion_id):
    minions = json.loads(subprocess.check_output([
        'salt-key',
        '--print', minion_id,
        '--out=json',
    ]).decode('utf-8'))

    existing_categories = minions.keys()
    if existing_categories:
        should_continue = input('Existing minions matching %s were found in %s, '
            'overwrite? [y/N]' % (minion_id, ', '.join(existing_categories)))
        return should_continue == 'y'

    return True


def trust_minion_key(minion_id, minion_pubkey):
    with open('/etc/salt/pki/master/minions/%s' % minion_id, 'wb') as fh:
        fh.write(minion_pubkey.encode('utf-8'))
        os.fchmod(fh.fileno(), 0o644)

    # If the minion connected before we trusted the key, remove the duplicate key in minions_pre
    pre_key_path = '/etc/salt/pki/master/minions_pre/%s' % minion_id
    try:
        pre_fh = open(pre_key_path)
    except IOError:
        return

    with pre_fh:
        pre_key = pre_fh.read()

    if pre_key.strip() == minion_pubkey.strip():
        print('Got early connection attempt from minion, removing pre-accept key')
        os.remove(pre_key_path)


def verify_minion_connection(client, minion_id, username):
    # The restart is needed since the minion might have attempted connecting to
    # the salt master before the key got trusted and thus might not be ready to
    # respond to a ping from the master
    prefix = 'sudo ' if username != 'root' else ''
    ssh_run_command(client,
        '{0}salt-call test.ping && {0}service salt-minion restart'.format(prefix),
        timeout=120)

    # Also test that the master can reach the minion, but the minion might take a moment
    # to start so try a couple times
    for i in range(5):
        try:
            subprocess.run(['salt', minion_id, 'test.ping'],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            if e.returncode == 1 and b'[Not connected]' in e.stdout:
                print('Failed connectivity check %d, trying again...' % (i + 1))
                time.sleep(2**i)
                continue
            print(e.stdout.decode('utf-8'))
            log_error(e.stderr.decode('utf-8'))
            raise
        else:
            print('Pinged %s successfully' % minion_id)
            break
    else:
        raise ConnectionError('Unable to ping new instance')

    authorized_keys_path = '/root/.ssh/authorized_keys'
    if username != 'root':
        authorized_keys_path = '/home/%s/.ssh/authorized_keys' % username
    ssh_run_command(client, 'rm %s' % authorized_keys_path)


def get_minion_pubkey(client, should_sudo):
    cmd = '%scat /etc/salt/pki/minion/minion.pub' % ('sudo ' if should_sudo else '')
    return ssh_run_command(client, cmd, log_stdout=False)
