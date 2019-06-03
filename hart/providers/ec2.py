import ipaddress
import json
import datetime
import sys

import boto3
import ifaddr
import paramiko
from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider

from .base import BaseLibcloudProvider, NodeSize, Region


# The pricing API is a supreme clusterfuck that requires lots of special care.
# One particular issue we run into when listing EC2 instance sizes in a given
# region is that the API doesn't allow you to filter on region, but on
# "location", which is the human-readable name of the region. There's no API to
# get the mapping between regions and the name, thus you either have to hardcode
# it like we do here and be forced to push and update whenever Amazon adds
# another region, or scrape the
# https://docs.aws.amazon.com/general/latest/gr/rande.html#ec2_region page,
# which will break if they change the html structure of that page. Opted for the
# hardcoding here for simplicity.
region_to_location_map = {
    'us-east-2': 'US East (Ohio)',
    'us-east-1': 'US East (N. Virginia)',
    'us-west-1': 'US West (N. California)',
    'us-west-2': 'US West (Oregon)',
    'ap-east-1': 'Asia Pacific (Hong Kong)',
    'ap-south-1': 'Asia Pacific (Mumbai)',
    'ap-northeast-3': 'Asia Pacific (Osaka-Local)',
    'ap-northeast-2': 'Asia Pacific (Seoul)',
    'ap-southeast-1': 'Asia Pacific (Singapore)',
    'ap-southeast-2': 'Asia Pacific (Sydney)',
    'ap-northeast-1': 'Asia Pacific (Tokyo)',
    'ca-central-1': 'Canada (Central)',
    'cn-north-1': 'China (Beijing)',
    'cn-northwest-1': 'China (Ningxia)',
    'eu-central-1': 'EU (Frankfurt)',
    'eu-west-1': 'EU (Ireland)',
    'eu-west-2': 'EU (London)',
    'eu-west-3': 'EU (Paris)',
    'eu-north-1': 'EU (Stockholm)',
    'sa-east-1': 'South America (Sao Paulo)',
}


class EC2Provider(BaseLibcloudProvider):
    username = 'admin'

    def __init__(self, aws_access_key_id, aws_secret_access_key, region):
        constructor = get_driver(Provider.EC2)
        self.driver = constructor(aws_access_key_id, aws_secret_access_key,
            region=region)
        # Libcloud's EC2 APIs for security groups just fails, thus keep boto
        # around for some EC2-specific stuff
        self.boto = boto3.client('ec2',
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.region = region


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


    def get_sizes(self):
        pricing = boto3.client('pricing',
            region_name='us-east-1',
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )
        sizes = []
        location = region_to_location_map[self.region]
        filters = [
            {'Field': 'currentGeneration', 'Value': 'Yes', 'Type': 'TERM_MATCH'},
            {'Field': 'operatingSystem', 'Value': 'Linux', 'Type': 'TERM_MATCH'},
            {'Field': 'location', 'Value': location, 'Type': 'TERM_MATCH'},
            {'Field': 'productFamily', 'Value': 'Compute Instance', 'Type': 'TERM_MATCH'},
            {'Field': 'capacityStatus', 'Value': 'Used', 'Type': 'TERM_MATCH'},
            {'Field': 'preInstalledSw', 'Value': 'NA', 'Type': 'TERM_MATCH'},
            {'Field': 'tenancy', 'Value': 'Shared', 'Type': 'TERM_MATCH'},
        ]
        paginator = pricing.get_paginator('get_products')
        results = paginator.paginate(
                ServiceCode='AmazonEC2',
                Filters=filters,
                FormatVersion='aws_v1',
        )
        for response in results:
            for stringified_data in response['PriceList']:
                data = json.loads(stringified_data)
                attributes = data['product']['attributes']
                extras = {
                    'family': attributes['instanceFamily'],
                    'network': attributes['networkPerformance'],
                }
                if 'cpuFreq' in attributes:
                    extras['cpuFreq'] = attributes['clockSpeed']

                offer = data['terms']['OnDemand'].popitem()[1]
                price_dimension = offer['priceDimensions'].popitem()[1]
                price_per_unit = float(price_dimension['pricePerUnit']['USD'])
                price_unit = price_dimension['unit']
                if price_unit == 'Hrs':
                    price = price_per_unit * 720
                else:
                    raise ValueError('Unknown price unit: %s' % price_unit)

                memory_value, memory_unit = attributes['memory'].split()
                if memory_unit == 'GiB':
                    memory = float(memory_value.replace(',', ''))
                else:
                    raise ValueError('unknown memory unit: %s' % memory_unit)

                sizes.append(NodeSize(
                    attributes['instanceType'],
                    memory,
                    int(attributes['vcpu']),
                    attributes['storage'],
                    price,
                    extras,
                ))

        sizes.sort(key=lambda s: s.monthly_cost)
        return sizes


    def get_regions(self):
        regions = []
        for region in self.driver.list_regions():

            # Skip regions inaccessible without extra setup
            if region.startswith('us-gov-') or region == 'ap-northeast-3' or region.startswith('cn-'):
                continue

            constructor = get_driver(Provider.EC2)
            region_provider = constructor(self.aws_access_key_id, self.aws_secret_access_key,
                region=region)
            for location in region_provider.list_locations():
                regions.append(Region(location.name, region_to_location_map[region]))
        regions.sort(key=lambda r: r.name)
        return regions


def get_host_public_ips():
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            string_ip = ip.ip[0] if isinstance(ip.ip, tuple) else ip.ip
            address = ipaddress.ip_address(string_ip)
            if address.is_global:
                yield '%s/%s' % (string_ip, address.max_prefixlen)
