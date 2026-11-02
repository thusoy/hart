import base64
import hashlib
import os
import sys
import tempfile
import traceback

import yaml

from . import utils
from .constants import DEBIAN_VERSIONS
from .ssh import get_verified_ssh_client, ssh_run_command, ssh_run_init_script
from .utils import get_private_ip


def create_master(
        minion_id,
        provider,
        region=None,
        size=None,
        salt_version=None,
        debian_codename='trixie',
        tags=None,
        private_networking=False,
        minion_config=None,
        grains=None,
        script=None,
        authorize_key=None,
        connect_via_private_ip=False,
        no_public_ip=False,
        **kwargs
        ):
    hart_node = create_master_node(
        minion_id,
        provider,
        region,
        size,
        salt_version,
        debian_codename,
        tags,
        private_networking,
        minion_config,
        grains,
        connect_via_private_ip=connect_via_private_ip,
        no_public_ip=no_public_ip,
        **kwargs
    )
    try:
        connect_to_master(hart_node, script, authorize_key)
    except:
        sys.stderr.write('Destroying master since it failed startup\n')
        # Not minions.destroy_node, since masters aren't in the minion store
        hart_node.provider.destroy_node(hart_node.node, extra=hart_node.node_extra)
        raise


def create_master_node(
        minion_id,
        provider,
        region=None,
        size=None,
        salt_version=None,
        debian_codename='trixie',
        tags=None,
        private_networking=False,
        minion_config=None,
        grains=None,
        connect_via_private_ip=False,
        no_public_ip=False,
        **kwargs
        ):
    ssh_canary = utils.create_token()
    cloud_init_template = utils.get_cloud_init_template('master.sh')
    default_minion_config = {
        'id': minion_id,
        'file_client': 'local',
        'state_verbose': False,
    }
    if minion_config is not None:
        default_minion_config.update(minion_config)

    cloud_init = cloud_init_template.render(**{
        'minion_config': yaml.dump(default_minion_config),
        'grains': yaml.dump({'grains': grains}) if grains else None,
        'salt_version': salt_version,
        'ssh_canary': ssh_canary,
        'wait_for_apt': DEBIAN_VERSIONS[debian_codename] >= 10,
        'permit_root_ssh': provider.username == 'root',
        'add_user': salt_version and int(salt_version[:salt_version.find('.')]) < 3006,
    })

    key_name = utils.build_ssh_key_name(minion_id)

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
                no_public_ip=no_public_ip,
                **kwargs)
            if no_public_ip:
                public_ip = None
                connect_ip = get_private_ip(node)
                print('Master running at %s (no public IP)' % connect_ip)
            else:
                node = provider.wait_for_public_ip(node)
                public_ip = node.public_ips[0]
                connect_ip = public_ip
                if connect_via_private_ip:
                    connect_ip = get_private_ip(node)
                    print('Master running at %s, connecting via private IP %s' % (
                        public_ip, connect_ip))
                else:
                    print('Master running at %s' % public_ip)
            hart_node = utils.HartNode(minion_id, public_ip, node, provider, ssh_key,
                ssh_canary, extra, connect_ip)
            return hart_node
        except:
            traceback.print_exc()
            if node:
                sys.stderr.write('Destroying node since it failed initialization\n')
                provider.destroy_node(node, extra)
            raise


def connect_to_master(hart_node, script, authorize_key=None):
    username = hart_node.provider.username
    connect_ip = hart_node.connect_ip or hart_node.public_ip
    with get_verified_ssh_client(
            connect_ip,
            hart_node.ssh_key,
            hart_node.ssh_canary,
            username) as client:
        hart_node.provider.wait_for_init_script(client, hart_node.node_extra)
        if authorize_key:
            ssh_run_command(client, 'echo "%s" >> ~/.ssh/authorized_keys' % authorize_key)
        if script:
            ssh_run_init_script(client, script)

        host_keys = ssh_run_command(client, 'cat /etc/ssh/ssh_host_*_key.pub',
            log_stdout=False)
        known_hosts_path = write_known_hosts(connect_ip, host_keys)
        print('Master created: %s@%s\nssh fingerprints:\n%s' % (
            username, connect_ip, '\n'.join(fingerprints(host_keys))))
        print('The host keys are trusted for this session in %s, connect with:\n'
            '    ssh -o UserKnownHostsFile=%s %s@%s' % (
                known_hosts_path, known_hosts_path, username, connect_ip))


def fingerprints(host_keys):
    '''The SHA256 fingerprints of the keys as ssh-keygen -l prints them'''
    for line in host_keys.splitlines():
        key_type, key = line.split()[:2]
        digest = hashlib.sha256(base64.b64decode(key)).digest()
        yield '%s SHA256:%s' % (key_type, base64.b64encode(digest).decode('ascii').rstrip('='))


def write_known_hosts(ip, host_keys):
    '''Write the host keys, read over the connection the canary verified, to a
    temporary known_hosts file. Lets the operator connect without trusting the
    keys on first use or adding them to ~/.ssh/known_hosts, which matters when
    they're only around until a restore from backup replaces them.'''
    directory = tempfile.mkdtemp(prefix='hart-')
    path = os.path.join(directory, 'known_hosts')
    with open(path, 'w') as fh:
        os.fchmod(fh.fileno(), 0o600)
        for line in host_keys.splitlines():
            key_type, key = line.split()[:2]
            fh.write('%s %s %s\n' % (ip, key_type, key))
    return path
