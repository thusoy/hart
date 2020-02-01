import abc
import contextlib
import time
import json
from collections import namedtuple

import paramiko


NodeSize = namedtuple('NodeSize', 'id memory cpu disk monthly_cost extras')
Region = namedtuple('Region', 'id name')


class BaseProvider(abc.ABC):
    username = 'root'


    def post_connect(self, hart_node):
        pass


    def add_create_minion_arguments(self, parser):
        '''Override this to provide kwargs to create_node'''
        pass


    def add_destroy_minion_arguments(self, parser):
        '''Override this to provide kwargs to destroy_node'''
        pass


    def add_list_regions_arguments(self, parser):
        '''Override this to provide kwargs to get_regions'''
        pass


    def add_list_sizes_arguments(self, parser):
        '''Override this to provide kwargs to get_sizes'''
        pass


    def generate_ssh_key(self): # pylint: disable=no-self-use
        # paramiko doesn't yet support creating Ed25519 keys :'(
        return paramiko.ECDSAKey.generate()


    def wait_for_init_script(self, client, extra=None):
        # Creds to https://stackoverflow.com/a/14158100 for a way to get the pid
        _, stdout, stderr = client.exec_command(
            'echo $$ && exec tail -f -n +1 /var/log/cloud-init-output.log')
        tail_pid = int(stdout.readline())
        for line in stdout:
            print(line, end='')
            if line.startswith('Cloud-init') and ' finished ' in line:
                stdout.channel.close()
                client.exec_command('kill %d' % tail_pid)
                break

        for line in stderr:
            print('Cloud-init stderr: %s' % line.strip())

        _, stdout, stderr = client.exec_command('cat /run/cloud-init/result.json', timeout=3)
        if stdout.channel.recv_exit_status() != 0:
            raise ValueError('Failed to get cloud-init status')

        cloud_init_result = json.loads(''.join(stdout))
        if cloud_init_result['v1']['errors']:
            raise ValueError('cloud-init failed: %s' % ', '.join(cloud_init_result['v1']['errors']))


    def wait_for_public_ip(self, node):
        if node.public_ips and node.public_ips[0] != '0.0.0.0':
            return node
        timeout = 180
        start_time = time.time()
        while True:
            time.sleep(2)
            node = self.get_node(node)
            if node.public_ips and node.public_ips[0] != '0.0.0.0':
                return node
            if time.time() - start_time > timeout:
                raise ValueError('Timed out waiting for node IP: %s' % node.id)


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
            print('Destroying %s ssh key' % self.__class__.__name__)
            self.destroy_remote_ssh_key(remote_key)


    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        '''Return a tuple of (remote_key, auth_key)'''
        raise NotImplementedError()


    def destroy_remote_ssh_key(self, remote_key):
        raise NotImplementedError()


    def get_size(self, size_name):
        raise NotImplementedError()


    def get_location(self, location_id):
        raise NotImplementedError()


    def destroy_node(self, node, extra=None, **kwargs):
        raise NotImplementedError()


    def get_node(self, node):
        '''node can be either a id or a Node as returned from `create_node`.'''
        raise NotImplementedError()


    def get_regions(self, **kwargs):
        raise NotImplementedError()


    def get_sizes(self, **kwargs):
        raise NotImplementedError()


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
        raise NotImplementedError()
