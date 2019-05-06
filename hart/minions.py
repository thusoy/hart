#!./venv/bin/python

import argparse
import base64
import binascii
import contextlib
import datetime
import getpass
import hashlib
import json
import os
import pwd
import subprocess
import sys
import time
import traceback
from collections import namedtuple

import yaml
from libcloud.compute.types import Provider, NodeState
from jinja2 import Template

from .ssh import get_verified_ssh_client, ssh_run_command
from .constants import DEBIAN_VERSIONS


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
        zone=None,
        subnet=None,
        security_groups=None,
        ):
    ssh_canary = base64.b64encode(os.urandom(30)).decode('utf-8')
    cloud_init_template = get_cloud_init_template()
    master_pubkey = get_master_pubkey()
    default_minion_config = {
        'id': minion_id,
    }
    if minion_config is not None:
        default_minion_config.update(minion_config)

    cloud_init = cloud_init_template.render(**{
        'minion_config': yaml.dump(default_minion_config),
        'ssh_canary': ssh_canary,
        'salt_branch': salt_branch,
        'debian_version': DEBIAN_VERSIONS[debian_codename],
        'debian_codename': debian_codename,
        'master_pubkey': master_pubkey,
    })

    key_name = build_ssh_key_name(minion_id)

    # if not check_existing_minion(minion_id):
    #     print('Existing minions were found and did want to overwrite, aborting')
    #     return

    with provider.create_temp_ssh_key(key_name) as (ssh_key, auth_key):
        print('have temp key!')
        node = None
        kwargs = {}
        if size:
            kwargs['size'] = size
        if zone:
            kwargs['zone'] = zone
        if subnet:
            kwargs['subnet'] = subnet
        if security_groups:
            kwargs['security_groups'] = security_groups
        try:
            node = provider.create_node(
                minion_id,
                region,
                debian_codename,
                auth_key,
                cloud_init,
                private_networking,
                tags,
                **kwargs)
            node = provider.wait_for_public_ip(node)
            print('Node running at %s' % node.public_ips[0])

            username = provider.username
            with get_verified_ssh_client(node.public_ips[0], ssh_key, ssh_canary, username) as client:
                wait_for_cloud_init(client)
                minion_pubkey = get_minion_pubkey(client, should_sudo=username != 'root')
                print(minion_pubkey)
                # trust_minion_key(minion_id, minion_pubkey)
                # print('Minion added: %s' % node.public_ips[0])
                # verify_minion_connection(client, minion_id)
                raise ValueError('stopping')
        except:
            traceback.print_exc()
            if node:
                sys.stderr.write('Destroying node since it failed initialization\n')
                provider.destroy_node(node)


def get_master_pubkey():
    return 'foo'
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
        should_continue = raw_input('Existing minions matching %s were found in %s, overwrite? [y/N]' % (
            minion_id, ', '.join(existing_categories)))
        return should_continue == 'y'

    return True


def trust_minion_key(minion_id, minion_pubkey):
    with open('/etc/salt/pki/master/minions/%s' % minion_id, 'wb') as fh:
        fh.write(minion_pubkey.encode('utf-8'))

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


def verify_minion_connection(client, minion_id):
    # The restart is needed since the minion might have attempted connecting to
    # the salt master before the key got trusted and thus might not be ready to
    # respond to a ping from the master
    ssh_run_command(client, 'salt-call test.ping && service salt-minion restart', timeout=15)

    # Give the minion some time to start before attempting another ping
    time.sleep(5)

    # Also test that the master can reach the minion
    subprocess.check_call(['salt', minion_id, 'test.ping'])

    ssh_run_command(client, 'rm /root/.ssh/authorized_keys')


def get_cloud_init_template(template_name='minion.sh'):
    template_path = os.path.join(os.path.dirname(__file__), 'cloud-init', template_name)
    with open(template_path) as fh:
        cloud_init_template = Template(fh.read())
    return cloud_init_template


def build_ssh_key_name(minion_id):
    current_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M')
    return 'temp-for-%s-at-%s' % (minion_id, current_date)


def wait_for_cloud_init(client):
    # Creds to https://stackoverflow.com/a/14158100 for a way to get the pid
    _, stdout, stderr = client.exec_command('echo $$ && exec tail -f /var/log/cloud-init-output.log')
    tail_pid = int(stdout.readline())
    for line in stdout:
        print(line, end='')
        if line.startswith('Cloud-init') and ' finished ' in line:
            stdout.channel.close()
            client.exec_command('kill %d' % tail_pid)
            break

    _, stdout, stderr = client.exec_command('cat /run/cloud-init/result.json', timeout=3)
    if stdout.channel.recv_exit_status() != 0:
        raise ValueError('Failed to get cloud-init status')

    cloud_init_result = json.loads(''.join(stdout))
    if cloud_init_result['v1']['errors']:
        raise ValueError('cloud-init failed: %s' % ', '.join(cloud_init_result['v1']['errors']))


def get_minion_pubkey(client, should_sudo):
    _, stdout, stderr = client.exec_command('%scat /etc/salt/pki/minion/minion.pub' % ('sudo ' if should_sudo else '',), timeout=3)
    if stdout.channel.recv_exit_status() != 0:
        raise ValueError('Failed to get minion pubkey: %s' % ''.join(stderr))

    return ''.join(stdout)
