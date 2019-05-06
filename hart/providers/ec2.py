import paramiko
from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider

from .base import BaseLibcloudProvider

class EC2Provider(BaseLibcloudProvider):
    username = 'admin'

    def __init__(self, aws_access_key_id, aws_secret_access_key, region):
        constructor = get_driver(Provider.EC2)
        self.driver = constructor(aws_access_key_id, aws_secret_access_key,
            region=region)


    def generate_ssh_key(self):
        # EC2 only supports RSA for ssh keys
        return paramiko.RSAKey.generate(2048)


    def create_node(self,
            minion_id,
            region,
            debian_codename,
            auth_key,
            cloud_init,
            private_networking,
            tags,
            size='t3.micro',
            zone=None,
            subnet=None,
            security_groups=None):
        if not zone:
            raise ValueError('You must specify the ec2 availability zone')

        size = self.get_size(size)
        image = self.get_image(debian_codename)

        subnet_ids = [subnet] if subnet else None
        subnets = self.driver.ex_list_subnets(subnet_ids=subnet_ids,
            filters={'availability-zone': zone})

        if not subnets and subnet:
            raise ValueError('No subnet matching %s in %s' % (subnet, zone))
        elif not subnets:
            raise ValueError('No available subnets in %s' % zone)
        elif len(subnets) > 1:
            raise ValueError('More than one subnet in availability zone, specify'
                ' which one to use: %s' % (', '.join(s.id for s in subnets)))

        subnet = subnets[0]

        node = self.driver.create_node(
            name=minion_id,
            size=size,
            image=image,
            location=self.get_location(zone),
            ex_keyname=auth_key,
            ex_userdata=cloud_init,
            ex_security_group_ids=security_groups,
            ex_subnet=subnet,
        )
        return node


    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        remote_key = self.driver.import_key_pair_from_string(key_name, public_key)
        return remote_key, key_name


    def get_image(self, debian_codename):
        official_debian_account = '379101102735'
        all_images = self.driver.list_images(ex_owner=official_debian_account, ex_filters={
            'architecture': 'x86_64',
        })
        dist_images = [image for image in all_images if image.name.startswith('debian-%s-' % debian_codename)]
        dist_images.sort(key=lambda i: i.name)
        return dist_images[-1]
