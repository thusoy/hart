import abc
import contextlib
import time

import paramiko
from libcloud.compute.base import NodeAuthSSHKey


class BaseLibcloudProvider(abc.ABC):
    username = 'root'
    driver = None

    def generate_ssh_key(self): # pylint: disable=no-self-use
        # paramiko doesn't yet support creating Ed25519 keys :'(
        return paramiko.ECDSAKey.generate()


    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        '''Return a tuple of (remote_key, auth_key)'''
        remote_key = self.driver.create_key_pair(key_name, public_key)
        auth_key = NodeAuthSSHKey(remote_key.public_key)
        return remote_key, auth_key


    @contextlib.contextmanager
    def create_temp_ssh_key(self, key_name):
        local_key = self.generate_ssh_key()
        # There's three different variants of the key here, the local key that
        # has the private part, the remote key which has the provider mapping to
        # delete it later, and the auth key, which is passed to the provider
        # again when creating the node to allow authentication.
        public_key = '%s %s' % (local_key.get_name(), local_key.get_base64())
        remote_key, auth_key = self.create_remote_ssh_key(key_name, local_key, public_key)
        print('Created temp ssh key')

        try:
            yield local_key, auth_key
        finally:
            print('Destroying %s ssh key' % self.driver.type)
            self.driver.delete_key_pair(remote_key)


    def wait_for_public_ip(self, node):
        if node.public_ips and node.public_ips[0] != '0.0.0.0':
            return node
        timeout = 180
        start_time = time.time()
        while True:
            time.sleep(2)
            node = self.get_updated_node(node)
            if node.public_ips and node.public_ips[0] != '0.0.0.0':
                return node
            if time.time() - start_time > timeout:
                raise ValueError('Timed out waiting for node IP: %s' % node.id)


    def get_updated_node(self, old_node):
        for node in self.driver.list_nodes():
            if node.id == old_node.id:
                return node

        raise ValueError('Updated node for %s not found' % old_node.id)


    def get_size(self, size_name):
        sizes = self.driver.list_sizes()
        for size in sizes:
            if size.name == size_name or size.id == size_name:
                # Allow targeting by id too
                return size

        raise ValueError('Unknown size: %s' % size_name)


    def get_location(self, location_id):
        for location in self.driver.list_locations():
            if location.id == location_id or location.name == location_id:
                return location

        raise ValueError('Location %s not found' % location_id)


    def destroy_node(self, node):
        self.driver.destroy_node(node)


    def get_node(self, node_id):
        for node in self.driver.list_nodes():
            if node_id in (node.id, node.name):
                return node

        raise ValueError('No node with id %s found' % node_id)
