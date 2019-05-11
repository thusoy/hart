import ipaddress
import datetime

import boto3
import ifaddr
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
        # Libcloud's EC2 APIs for security groups just fails, thus keep boto
        # around for EC2-specific stuff
        self.boto = boto3.client('ec2',
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )


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
            subnet=None):
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

        temp_security_group = self.create_temp_security_group(minion_id)

        node = self.driver.create_node(
            name=minion_id,
            size=size,
            image=image,
            location=self.get_location(zone),
            ex_keyname=auth_key,
            ex_userdata=cloud_init,
            ex_security_group_ids=temp_security_group,
            ex_subnet=subnet,
        )
        return node, temp_security_group


    def create_temp_security_group(self, minion_id):
        # libcloud's ex_create_security_group fails with signature errors, thus
        # ignore libcloud for this and use boto instead.
        current_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
        name = 'temp-for-%s-%s' % (minion_id, current_date)

        # Get the external IPs for the current host
        external_ips = list(get_host_public_ips())
        if not external_ips:
            raise ValueError('Could not find any public IPs on the current '
                'host and thus wont be able to connect to the new node')

        group = self.boto.create_security_group(
            GroupName=name,
            Description='Temporary group for initial saltmaster ssh initialization',
        )
        group_id = group['GroupId']

        self.boto.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[{
                'IpProtocol': 'tcp',
                'FromPort': 22,
                'ToPort': 22,
                'IpRanges': [{'CidrIp': ip} for ip in external_ips],
            }]
        )

        return group_id


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


    def post_ssh_cleanup(self, hart_node):
        # Delete the temp security group that allowed ssh
        # Detach the security group from the instance. An instance must have at
        # least one security group, so we attach the VPC default group.
        self.delete_node_security_group(hart_node.node, hart_node.node_extra)


    def delete_node_security_group(self, node, group_id):
        print('Deleting temporary security group')
        response = self.boto.describe_security_groups(GroupNames=['default'])
        default_group = response['SecurityGroups'][0]
        self.boto.modify_instance_attribute(InstanceId=node.id, Groups=[default_group['GroupId']])
        response = self.boto.delete_security_group(GroupId=group_id)


    def destroy_node(self, node, extra=None):
        if extra is not None:
            self.delete_node_security_group(node, extra)

        self.driver.destroy_node(node)


def get_host_public_ips():
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            string_ip = ip.ip[0] if isinstance(ip.ip, tuple) else ip.ip
            address = ipaddress.ip_address(string_ip)
            if address.is_global:
                yield '%s/%s' % (string_ip, address.max_prefixlen)
