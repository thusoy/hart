import contextlib
import datetime
import time

from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider, NodeState
from libcloud.utils.py3 import httplib

from .base import BaseLibcloudProvider


class VultrProvider(BaseLibcloudProvider):

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
            size='201'):
        size = self.get_size(size)
        image = self.get_image(debian_codename)
        location = self.get_location(region)
        # Vultr has replaced cloud-init with their own startup script
        # implementation. This doesn't seem to be reflected in their docs,
        # but a comment here indicates as much:
        # https://discuss.vultr.com/discussion/582/cloud-init-user-data-testing/p3
        script_id = self.create_temp_startup_script(minion_id, cloud_init)
        node = self.driver.create_node(minion_id, size, image, location, ex_ssh_key_ids=[
            auth_key.id
        ], ex_create_attr={
            'script_id': script_id,
            'notify_activate': False,
            'enable_private_network': private_networking,
            'hostname': minion_id,
            'tag': tags,
        })
        # Vultr has a race condition where if the ssh key is deleted too early,
        # ie before the node has read it on startup, it won't be available to
        # use for logging in. Thus we delay the return here until the node state
        # indicates it's ready to continue.
        start_time = time.time()
        while time.time() - start_time < 180:
            print('Waiting for node to boot (%s)' % node.state)
            time.sleep(2)
            node = self.get_updated_node(node)
            if node.state != NodeState.PENDING:
                print('Node in state %s, continuing' % node.state)
                break
        else:
            # Can't auto-destroy since the API doesn't enable destroying nodes
            # before they are initialized
            raise ValueError('Failed to start node before timeout')

        return node, script_id


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


    def delete_startup_script(self, script_id):
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
            if image.extra['family'] == 'debian' and image.extra['arch'] == 'x64' and debian_codename in image.name:
                return image

        raise ValueError('Debian %s image not found' % debian_codename)


    def destroy_node(self, node, extra=None):
        if extra is not None:
            self.delete_startup_script(extra)

        # Vultr doesn't handle deleting nodes that haven't finished
        # initialization well, wait for the node to finish boot before
        # destroying it
        timeout = 180
        start_time = time.time()
        while True:
            time.sleep(3)
            node = self.get_updated_node(node)
            if node.state == NodeState.RUNNING:
                self.driver.destroy_node(node)
                break
            if time.time() - start_time > timeout:
                raise ValueError('Timed out waiting to delete initializing node: %s' % node.id)


    def wait_for_init_script(self, client, script_id):
        # If we delete the startup script any earlier it might not get onto the node and
        # boot might fail
        self.delete_startup_script(script_id)

        # Creds to https://stackoverflow.com/a/14158100 for a way to get the pid
        _, stdout, stderr = client.exec_command('echo $$ && exec tail -f /tmp/firstboot.log')
        tail_pid = int(stdout.readline())
        for line in stdout:
            print(line, end='')
            if line.startswith('Hart init script complete'):
                stdout.channel.close()
                client.exec_command('kill %d' % tail_pid)
                return

        raise ValueError('Failed to complete init script: %s' % ''.join(stderr).strip())
