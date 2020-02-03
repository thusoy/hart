from libcloud.compute.base import NodeAuthSSHKey

from .base import BaseProvider, Region
from ..exceptions import UserError


class BaseLibcloudProvider(BaseProvider):
    driver = None

    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        '''Return a tuple of (remote_key, auth_key)'''
        remote_key = self.driver.create_key_pair(key_name, public_key)
        auth_key = NodeAuthSSHKey(remote_key.public_key)
        return remote_key, auth_key


    def destroy_remote_ssh_key(self, remote_key):
        self.driver.delete_key_pair(remote_key)


    def get_size(self, size_name):
        sizes = self.driver.list_sizes()
        for size in sizes:
            if size_name in (size.id, size.name):
                return size

        raise UserError('Unknown size: %s' % size_name)


    def get_location(self, location_id):
        for location in self.driver.list_locations():
            if location_id in (location.name, location.id):
                return location

        raise UserError('Location %s not found' % location_id)


    def destroy_node(self, node, extra=None, **kwargs):
        self.driver.destroy_node(node)


    def get_node(self, node_id):
        if not isinstance(node_id, str):
            node_id = node_id.name
        for node in self.driver.list_nodes():
            if node_id in (node.id, node.name):
                return node

        raise UserError('No node with id %s found in provider %s' % (
            node_id, self.__class__.__name__))


    def get_regions(self, **kwargs):
        regions = []
        for location in self.driver.list_locations():
            regions.append(Region(location.id, location.name))
        regions.sort(key=lambda r: r.name)
        return regions
