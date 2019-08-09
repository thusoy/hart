import ipaddress
import json
import datetime
import sys

import boto3
import ifaddr
import paramiko
from libcloud.compute.base import Node
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
    'me-south-1': 'Middle East (Bahrain)',
}


class EC2Provider(BaseLibcloudProvider):
    username = 'admin'

    def __init__(self, aws_access_key_id, aws_secret_access_key, region):
        self.ec2 = boto3.client('ec2',
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


    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        import_response = self.ec2.import_key_pair(KeyName=key_name, PublicKeyMaterial=public_key)
        assert import_response['ResponseMetadata']['HTTPStatusCode'] == 200
        return key_name, key_name


    def destroy_remote_ssh_key(self, remote_key):
        self.ec2.delete_key_pair(KeyName=remote_key)


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

        subnet_ids = [subnet] if subnet else []
        subnet_response = self.ec2.describe_subnets(SubnetIds=subnet_ids,
            Filters=[{'Name': 'availability-zone', 'Values': [zone]}])
        subnets = subnet_response['Subnets']

        if not subnets and subnet:
            raise ValueError('No subnet matching %s in %s' % (subnet, zone))
        elif not subnets:
            raise ValueError('No available subnets in %s' % zone)
        elif len(subnets) > 1:
            raise ValueError('More than one subnet in availability zone, specify'
                ' which one to use: %s' % (', '.join(s.id for s in subnets)))

        subnet = subnets[0]
        temp_security_group = self.create_temp_security_group(minion_id)
        create_response = self.ec2.run_instances(
            ImageId=image['ImageId'],
            InstanceType=size,
            KeyName=auth_key,
            Placement={'AvailabilityZone': zone},
            UserData=cloud_init,
            MinCount=1,
            MaxCount=1,
            NetworkInterfaces=[{
                'AssociatePublicIpAddress': True,
                'DeleteOnTermination': True,
                'DeviceIndex': 0,
                'SubnetId': subnet['SubnetId'],
                'Groups': [temp_security_group],
            }],
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': minion_id}],
            }],
        )
        instance = create_response['Instances'][0]

        node = Node(id=instance['InstanceId'], name=minion_id, state=instance['State']['Name'],
            public_ips=[], private_ips=[instance['PrivateIpAddress']],
            driver=self.ec2, created_at=instance['LaunchTime'], extra=None)
        return node, temp_security_group


    def get_updated_node(self, old_node):
        instance_response = self.ec2.describe_instances(InstanceIds=[old_node.id])
        instance = instance_response['Reservations'][0]['Instances'][0]
        public_ip = instance.get('PublicIpAddress')
        public_ips = [public_ip] if public_ip else []
        name = None
        for tag in instance['Tags']:
            if tag['Key'] == 'Name':
                name = tag['Value']
                break
        return Node(id=instance['InstanceId'], name=name, state=instance['State']['Name'],
            public_ips=public_ips, private_ips=[instance['PrivateIpAddress']],
            driver=self.ec2, created_at=instance['LaunchTime'], extra=None)


    def create_temp_security_group(self, minion_id):
        current_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
        name = 'temp-for-%s-%s' % (minion_id, current_date)

        # Get the external IPs for the current host
        external_ips = list(get_host_public_ips())
        if not external_ips:
            raise ValueError('Could not find any public IPs on the current '
                'host and thus wont be able to connect to the new node')

        group = self.ec2.create_security_group(
            GroupName=name,
            Description='Temporary group for initial saltmaster ssh initialization',
        )
        group_id = group['GroupId']

        self.ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[{
                'IpProtocol': 'tcp',
                'FromPort': 22,
                'ToPort': 22,
                'IpRanges': [{'CidrIp': ip} for ip in external_ips],
            }]
        )

        return group_id


    def get_image(self, debian_codename):
        official_debian_account = '379101102735'
        image_response = self.ec2.describe_images(Owners=[official_debian_account], Filters=[{
            'Name': 'architecture',
            'Values': ['x86_64'],
        }])
        dist_images = [image for image in image_response['Images'] if image['Name'].startswith('debian-%s-' % debian_codename)]
        dist_images.sort(key=lambda i: i['Name'])
        return dist_images[-1]


    def post_connect(self, hart_node):
        # Delete the temp security group that allowed ssh
        # Detach the security group from the instance. An instance must have at
        # least one security group, so we attach the VPC default group.
        self.delete_node_security_group(hart_node.node, hart_node.node_extra)


    def delete_node_security_group(self, node, group_id):
        print('Deleting temporary security group')
        response = self.ec2.describe_security_groups(GroupNames=['default'])
        default_group = response['SecurityGroups'][0]
        self.ec2.modify_instance_attribute(InstanceId=node.id, Groups=[default_group['GroupId']])
        response = self.ec2.delete_security_group(GroupId=group_id)


    def destroy_node(self, node, extra=None):
        if extra is not None:
            self.delete_node_security_group(node, extra)

        self.ec2.terminate_instances(InstanceIds=[node.id])


    def get_size(self, size_name):
        return size_name


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
        response = self.ec2.describe_regions()
        for region in response['Regions']:
            region_boto = boto3.client('ec2',
                region_name=region['RegionName'],
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            )
            az_response = region_boto.describe_availability_zones()
            for zone in az_response['AvailabilityZones']:
                # Don't fail if we don't know the name of the region to avoid
                # crashing for new regions we don't know about yet
                region_name = region_to_location_map.get(zone['RegionName'], 'Unknown')
                regions.append(Region(zone['ZoneName'], region_name))
        regions.sort(key=lambda r: r.name)
        return regions


def get_host_public_ips():
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            string_ip = ip.ip[0] if isinstance(ip.ip, tuple) else ip.ip
            address = ipaddress.ip_address(string_ip)
            if address.is_global:
                yield '%s/%s' % (string_ip, address.max_prefixlen)
