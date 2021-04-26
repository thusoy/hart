import base64
import hashlib

from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider

from ..constants import DEBIAN_VERSIONS
from .base import NodeSize
from .libcloud import BaseLibcloudProvider


class DOProvider(BaseLibcloudProvider):
    alias = 'do'
    default_size = 's-1vcpu-1gb'

    def __init__(self, token, **kwargs):
        constructor = get_driver(Provider.DIGITAL_OCEAN)
        self.driver = constructor(token, api_version='v2')


    def add_create_minion_arguments(self, parser):
        parser.add_argument('-6', '--enable-ipv6', action='store_true',
            help='Enable IPv6 on the droplet')


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

        key_fingerprint = pubkey_to_fingerprint(auth_key.pubkey)
        size = self.get_size(size)
        image = self.get_image(debian_codename)
        location = self.get_location(region)
        node = self.driver.create_node(minion_id, size, image, location, ex_user_data=cloud_init, ex_create_attr={
            'ssh_keys': [key_fingerprint],
            'private_networking': private_networking,
            'tags': tags,
            'ipv6': kwargs.get('enable_ipv6'),
        })
        return node, None


    def get_image(self, debian_codename):
        target_image = 'debian-%d-x64' % DEBIAN_VERSIONS[debian_codename]
        for image in self.driver.list_images():
            if image.extra['slug'] == target_image:
                return image
        raise ValueError('Image for %s not found' % debian_codename)


    def get_sizes(self, **kwargs):
        sizes = []
        for size in self.driver.list_sizes():
            sizes.append(NodeSize(
                size.name,
                size.ram/2**10,
                size.extra['vcpus'],
                '%d GB SSD' % size.disk,
                size.price*720,
                {'regions': size.extra['regions']},
            ))

        sizes.sort(key=lambda s: s.monthly_cost)
        return sizes


def pubkey_to_fingerprint(pubkey):
    '''Encodes the key fingerprint as colon-separated hex pairs, like ba:5e:ba:11.'''
    base64_bytes = pubkey.split(' ')[1]
    key_blob = base64.b64decode(base64_bytes)
    hex_encoded = hashlib.md5(key_blob).hexdigest()
    return ':'.join(a + b for a, b in zip(hex_encoded[::2], hex_encoded[1::2]))
