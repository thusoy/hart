import datetime
import json
import time
import subprocess

from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider, NodeState
from libcloud.utils.py3 import httplib

from .base import NodeSize
from .libcloud import BaseLibcloudProvider
from ..constants import DEBIAN_VERSIONS
from ..exceptions import UserError


class VultrProvider(BaseLibcloudProvider):
    alias = 'vultr'
    default_size = '201'

    def __init__(self, token, **kwargs):
        constructor = get_driver(Provider.VULTR)
        self.driver = constructor(token)


    def create_node(self,
            minion_id,
            region,
            debian_codename,
            auth_key,
            cloud_init,
            private_networking,
            tags,
            size=None,
            **kwargs):
        if size is None:
            size = self.default_size

        size = self.get_size(size)
        image = self.get_image(debian_codename)
        location = self.get_location(region)
        # Vultr has replaced cloud-init with their own startup script
        # implementation. This doesn't seem to be reflected in their docs,
        # but a comment here indicates as much:
        # https://discuss.vultr.com/discussion/582/cloud-init-user-data-testing/p3
        script_id = self.create_temp_startup_script(minion_id, cloud_init)
        node_extra = {
            'script_id': script_id,
            'private_networking': private_networking,
            'debian_codename': debian_codename,
        }
        tag = None
        if len(tags) > 1:
            raise UserError('Can only set a single tag on vultr')
        elif tags:
            tag = tags[0]

        node = self.driver.create_node(minion_id, size, image, location, ex_ssh_key_ids=[
            auth_key.id
        ], ex_create_attr={
            'script_id': script_id,
            'notify_activate': False,
            'enable_private_network': 'yes' if private_networking else 'no',
            'hostname': minion_id,
            'tag': tag,
        })
        # Vultr has a race condition where if the ssh key is deleted too early,
        # ie before the node has read it on startup, it won't be available to
        # use for logging in. Thus we delay the return here until the node state
        # indicates it's ready to continue.
        start_time = time.time()
        while time.time() - start_time < 180:
            print('Waiting for node to boot (%s)' % node.state)
            time.sleep(2)
            node = self.get_node(node)
            if node.state != NodeState.PENDING:
                print('Node in state %s, continuing' % node.state)
                break
        else:
            # Can't auto-destroy since the API doesn't enable destroying nodes
            # before they are initialized
            raise ValueError('Failed to start node before timeout')

        return node, node_extra


    def create_temp_startup_script(self, minion_id, cloud_init):
        current_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
        params = {
            'name': 'temp-script-for-%s-%s' % (minion_id, current_date),
            'script': cloud_init,
        }

        result = self.driver.connection.post('/v1/startupscript/create', params)
        if result.status != httplib.OK:
            raise ValueError('Failed to create temp startupscript')

        script_id = result.object['SCRIPTID']
        return script_id


    def delete_startup_script(self, node_extra):
        if not node_extra['script_id']:
            # The delete might be called multiple times on error, prevent it
            # from trying to delete the script twice
            return

        script_id = node_extra['script_id']
        node_extra['script_id'] = None

        print('Start up script with id %d' % script_id)

        params = {'SCRIPTID': script_id}
        result = self.driver.connection.post('/v1/startupscript/destroy', params)
        if result.status != httplib.OK:
            print('Failed to delete temp startupscript %s' % script_id)


    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        # The vultr provider mistakenly returns a success bool instead of the key pair.
        # PR from 2017 that fixes it: https://github.com/apache/libcloud/pull/998
        # ¯\_(ツ)_/¯s
        self.driver.create_key_pair(key_name, public_key)
        key_pairs = self.driver.list_key_pairs()
        for key_pair in key_pairs:
            if key_pair.name == key_name:
                break
        else:
            raise ValueError('Failed to create ssh key pair')
        return key_pair, key_pair


    def get_image(self, debian_codename):
        for image in self.driver.list_images():
            if (image.extra['family'] == 'debian'
                    and image.extra['arch'] == 'x64'
                    and debian_codename in image.name):
                return image

        raise ValueError('Debian %s image not found' % debian_codename)


    def destroy_node(self, node, extra=None, **kwargs):
        if extra is not None:
            self.delete_startup_script(extra)

        # Vultr doesn't handle deleting nodes that haven't finished
        # initialization well, wait for the node to finish boot before
        # destroying it
        timeout = 180
        start_time = time.time()
        while True:
            time.sleep(3)
            node = self.get_node(node)
            if node.state == NodeState.RUNNING:
                self.driver.destroy_node(node)
                break
            if time.time() - start_time > timeout:
                raise ValueError('Timed out waiting to delete initializing node: %s' % node.id)


    def wait_for_init_script(self, client, node_extra):
        # If we delete the startup script any earlier it might not get onto the node and
        # boot might fail
        self.delete_startup_script(node_extra)

        if DEBIAN_VERSIONS[node_extra['debian_codename']] >= 11:
            # For bullseye and newer the base image uses the standard cloud init boot log
            # location and we don't need the custom logic here
            super().wait_for_init_script(client, node_extra)
            return

        # Creds to https://stackoverflow.com/a/14158100 for a way to get the pid
        _, stdout, stderr = client.exec_command('echo $$ && exec tail -f /var/log/firstboot.log')
        tail_pid = int(stdout.readline())
        for line in stdout:
            print(line, end='')
            if line.startswith('hart-init-complete'):
                stdout.channel.close()
                client.exec_command('kill %d' % tail_pid)
                return

        raise ValueError('Failed to complete init script: %s' % ''.join(stderr).strip())


    def get_sizes(self, **kwargs):
        sizes = []
        for size in self.driver.list_sizes():
            sizes.append(NodeSize(
                size.id,
                size.ram/2**10,
                size.extra['vcpu_count'],
                '%d GB SSD' % size.disk,
                size.price,
                {},
            ))

        sizes.sort(key=lambda s: s.monthly_cost)
        return sizes


    def post_connect(self, hart_node):
        if not hart_node.node_extra['private_networking']:
            return

        # For private networking to work for the node it needs to be attached
        # inside the node too. Thus get the private IP that was assigned from
        # the API and add it.
        response = self.driver.connection.get('/v1/server/list_ipv4?SUBID=%s' % hart_node.node.id)
        networks = response.object[hart_node.node.id]
        ip = None
        netmask = None
        for network in networks:
            if network['type'] == 'private':
                ip = network['ip']
                netmask = network['netmask']
                break

        if ip is None:
            raise ValueError("Couldn't find private network attached to server")

        interface = 'ens7'
        enable_network_interfaces_d(hart_node.minion_id)
        add_ip_to_device(hart_node.minion_id, 'private', interface, ip, netmask)
        bring_up_interface_with_label(hart_node.minion_id, interface)


def add_ip(minion_id, current_device_ip, ip, netmask, ip_kind):
    '''
    :param minion_id: The minion id
    :param current_device_ip: An IP the device holds today we can use to identify it.
    :param ip: The new ip to attach
    :param ip_kind: The kind of IP to add. 'reserved' or 'private'.
    '''
    _, next_label = get_network_device_name_for_ip(minion_id, current_device_ip)
    enable_network_interfaces_d(minion_id)
    add_ip_to_device(minion_id, ip_kind, next_label, ip, netmask)
    bring_up_interface_with_label(minion_id, next_label)


def get_network_device_name_for_ip(minion_id, current_device_ip):
    '''
    Return a tuple (device_name, next_available_label).
    '''
    interfaces = get_interfaces(minion_id)
    return get_device_and_next_label_from_interfaces(interfaces, current_device_ip)


def get_interfaces(minion_id):
    output = subprocess.check_output([
        'salt',
        minion_id,
        'network.interfaces',
        '--out=json',
    ]).decode('utf-8')
    return json.loads(output)[minion_id]


def get_device_and_next_label_from_interfaces(interfaces, current_device_ip):
    device_name = None
    for name, interface in interfaces.items():
        current_device_labels = set()
        for address in interface.get('inet', []):
            label = address.get('label')
            if label:
                current_device_labels.add(label)

            if address['address'] != current_device_ip:
                continue

            device_name = name

        if device_name:
            break

    if device_name is None:
        raise ValueError('Could not find network device with ip %s' %
            current_device_ip)

    next_label_num = 0
    next_label = '%s:%d' % (device_name, next_label_num)
    while next_label in current_device_labels:
        next_label_num += 1
        next_label = '%s:%d' % (device_name, next_label_num)

    return device_name, next_label


def enable_network_interfaces_d(minion_id):
    subprocess.run([
        'salt',
        minion_id,
        'file.replace',
        '/etc/network/interfaces',
        '^#source /etc/network/interfaces.d/\\*$',
        'source /etc/network/interfaces.d/*',
        'append_if_not_found=True',
    ], check=True)


def add_ip_to_device(minion_id, ip_kind, label, ip, netmask):
    '''
    :param ip_kind: What kind of IP this is. Either 'reserved' or 'private'.
    '''
    mtu = 1450 if ip_kind == 'private' else None
    lines = [
        'auto %s' % label,
        'iface %s inet static' % label,
        'address %s' % ip,
        'netmask %s' % netmask,
    ]
    if mtu:
        lines.append('mtu %d' % mtu)

    subprocess.run([
        'salt',
        minion_id,
        'file.write',
        '/etc/network/interfaces.d/20-hart-%s-ip' % ip_kind,
        'args=[%s]' % ', '.join("'%s'" % line for line in lines),
    ], check=True)


def bring_up_interface_with_label(minion_id, label):
    subprocess.run([
        'salt',
        minion_id,
        'cmd.run',
        'ifup %s' % label,
    ], check=True)
