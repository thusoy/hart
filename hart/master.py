import sys
import traceback

import yaml

from . import utils
from .constants import DEBIAN_VERSIONS
from .ssh import get_verified_ssh_client, ssh_run_command, ssh_run_init_script


def create_master(
        minion_id,
        provider,
        region=None,
        size=None,
        salt_version=None,
        debian_codename='bookworm',
        tags=None,
        private_networking=False,
        minion_config=None,
        grains=None,
        script=None,
        authorize_key=None,
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
        **kwargs
    )
    try:
        connect_to_master(hart_node, script, authorize_key)
    except:
        sys.stderr.write('Destroying master since it failed startup\n')
        hart_node.provider.destroy_node(hart_node.node, extra=hart_node.node_extra)
        raise


def create_master_node(
        minion_id,
        provider,
        region=None,
        size=None,
        salt_version=None,
        debian_codename='bookworm',
        tags=None,
        private_networking=False,
        minion_config=None,
        grains=None,
        **kwargs
        ):
    ssh_canary = utils.create_token()
    cloud_init_template = utils.get_cloud_init_template('master.sh')
    default_minion_config = {
        'id': minion_id,
        'user': 'salt',
        'file_client': 'local',
        'state_verbose': False,
    }
    if minion_config is not None:
        default_minion_config.update(minion_config)

    cloud_init = cloud_init_template.render(**{
        'random_seed': utils.create_token(),
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
                **kwargs)
            node = provider.wait_for_public_ip(node)
            public_ip = node.public_ips[0]
            print('Master running at %s' % public_ip)
            return utils.HartNode(minion_id, public_ip, node, provider, ssh_key, ssh_canary, extra)
        except:
            traceback.print_exc()
            if node:
                sys.stderr.write('Destroying node since it failed initialization\n')
                provider.destroy_node(node, extra)
            raise


def connect_to_master(hart_node, script, authorize_key=None):
    username = hart_node.provider.username
    with get_verified_ssh_client(
            hart_node.public_ip,
            hart_node.ssh_key,
            hart_node.ssh_canary,
            username) as client:
        hart_node.provider.wait_for_init_script(client, hart_node.node_extra)
        if authorize_key:
            ssh_run_command(client, 'echo "%s" >> ~/.ssh/authorized_keys' % authorize_key)
        if script:
            ssh_run_init_script(client, script)

        master_pubkeys = ssh_run_command(client,
            'for pubkey in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$pubkey"; done',
            log_stdout=False)
        print('Master created: %s@%s\nssh fingerprints: \n%s' % (
            username, hart_node.public_ip, master_pubkeys))
