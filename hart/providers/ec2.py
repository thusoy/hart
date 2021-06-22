import ipaddress
import json
import datetime
import sys
import time

import boto3
import ifaddr
import paramiko
from libcloud.compute.base import Node

from .base import BaseProvider, NodeSize, Region
from ..constants import DEBIAN_VERSIONS
from ..exceptions import UserError
from ..utils import remove_argument_from_parser


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
    'af-south-1': 'Africa (Cape Town)',
    'ap-east-1': 'Asia Pacific (Hong Kong)',
    'ap-northeast-1': 'Asia Pacific (Tokyo)',
    'ap-northeast-2': 'Asia Pacific (Seoul)',
    'ap-northeast-3': 'Asia Pacific (Osaka)',
    'ap-south-1': 'Asia Pacific (Mumbai)',
    'ap-southeast-1': 'Asia Pacific (Singapore)',
    'ap-southeast-2': 'Asia Pacific (Sydney)',
    'ca-central-1': 'Canada (Central)',
    'cn-north-1': 'China (Beijing)',
    'cn-northwest-1': 'China (Ningxia)',
    'eu-central-1': 'EU (Frankfurt)',
    'eu-north-1': 'EU (Stockholm)',
    'eu-south-1': 'EU (Milan)',
    'eu-west-1': 'EU (Ireland)',
    'eu-west-2': 'EU (London)',
    'eu-west-3': 'EU (Paris)',
    'me-south-1': 'Middle East (Bahrain)',
    'sa-east-1': 'South America (Sao Paulo)',
    'us-east-1': 'US East (N. Virginia)',
    'us-east-2': 'US East (Ohio)',
    'us-west-1': 'US West (N. California)',
    'us-west-2': 'US West (Oregon)',
}


class EC2Provider(BaseProvider):
    username = 'admin'
    alias = 'ec2'
    default_size = 't3.micro'

    def __init__(self, aws_access_key_id, aws_secret_access_key, region=None):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.region = region
        self._ec2 = None


    @property
    def ec2(self):
        # Construct this lazily to prevent the region from having to be
        # specified to list regions or sizes
        if self._ec2:
            return self._ec2

        self._ec2 = boto3.client('ec2',
            region_name=self.region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )
        return self._ec2


    def generate_ssh_key(self):
        # EC2 only supports RSA for ssh keys
        return paramiko.RSAKey.generate(2048)


    def add_create_minion_arguments(self, parser):
        def split_csv_keyval(clistring):
            ret = {}
            for key_value_pair in clistring.split(','):
                if not '=' in key_value_pair:
                    raise UserError('EC2 requires tags to be key=value pairs')

                key, value = key_value_pair.split('=', 1)
                ret[key] = value
            return ret

        remove_argument_from_parser(parser, '--tags')
        parser.add_argument('-t', '--tags', type=split_csv_keyval, default={},
            help='Tags to add to the new node, comma-separated list of key=value pairs.')

        parser.add_argument('-z', '--zone', help='AWS availability zone')
        parser.add_argument('--subnet',
            help='AWS: The subnet to launch the node in')
        parser.add_argument('--volume-size', type=int,
            help='The size of the EBS drive')
        parser.add_argument('--volume-type',
            choices=('standard', 'io1', 'gp2', 'sc1', 'st1'),
            help='The type of EBS drive to mount')
        parser.add_argument('--volume-iops', type=int,
            help='How many IOPS to provision (only applies to io1 volumes)')
        parser.add_argument('--connection-gateway',
            help="If the saltmaster's outbound IP can't be automatically detected, "
            "specify the CIDR range to allow through the firewall to the minion here.")


    def add_list_regions_arguments(self, parser):
        parser.add_argument('-z', '--include-zones', action='store_true')


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
            size=None,
            **kwargs):
        if size is None:
            size = self.default_size

        zone = kwargs.get('zone')
        if not zone:
            raise UserError('You must specify the ec2 availability zone')

        size = self.get_size(size)
        image = self.get_image(debian_codename)

        subnet = kwargs.get('subnet')
        subnet_ids = [subnet] if subnet else []
        subnet_response = self.ec2.describe_subnets(SubnetIds=subnet_ids,
            Filters=[{'Name': 'availability-zone', 'Values': [zone]}])
        subnets = subnet_response['Subnets']

        if not subnets and subnet:
            raise UserError('No subnet matching %s in %s' % (subnet, zone))
        elif not subnets:
            raise UserError('No available subnets in %s' % zone)
        elif len(subnets) > 1:
            subnet_summary = []
            for subnet in subnets:
                for tag in subnet.get('Tags', []):
                    if tag['Key'] == 'Name':
                        subnet_summary.append('%s (%s)' % (subnet['SubnetId'], tag['Value']))
                        break
                else:
                    subnet_summary.append(subnet['SubnetId'])
            raise UserError('More than one subnet in availability zone, specify'
                ' which one to use: %s' % (', '.join(subnet_summary)))

        subnet = subnets[0]
        temp_security_group = self.create_temp_security_group(minion_id,
            kwargs.get('connection_gateway'), subnet['VpcId'])

        block_devices = []
        volume_type = kwargs.get('volume_type')
        volume_size = kwargs.get('volume_size')
        if volume_type or volume_size:
            ebs = {}
            # iops is only supported for io1 volumes and thus can only be
            # specified with --volume-type
            iops = kwargs.get('volume_iops')
            if iops:
                ebs['Iops'] = iops

            if volume_type:
                ebs['VolumeType'] = volume_type

            # The debian images automatically expand the filesystem to match on boot
            if volume_size:
                ebs['VolumeSize'] = volume_size
            block_devices.append({
                'DeviceName': image['RootDeviceName'],
                'Ebs': ebs,
            })

        tag_specifications = [{'Key': 'Name', 'Value': minion_id}]
        for key, val in tags.items():
            tag_specifications.append({
                'Key': key,
                'Value': val,
            })

        create_response = self.ec2.run_instances(
            ImageId=image['ImageId'],
            InstanceType=size,
            KeyName=auth_key,
            Placement={'AvailabilityZone': zone},
            UserData=cloud_init,
            MinCount=1,
            MaxCount=1,
            BlockDeviceMappings=block_devices,
            NetworkInterfaces=[{
                'AssociatePublicIpAddress': True,
                'DeleteOnTermination': True,
                'DeviceIndex': 0,
                'SubnetId': subnet['SubnetId'],
                'Groups': [temp_security_group],
            }],
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': tag_specifications,
            }],
        )
        instance = create_response['Instances'][0]

        node = Node(id=instance['InstanceId'], name=minion_id, state=instance['State']['Name'],
            public_ips=[], private_ips=[instance['PrivateIpAddress']],
            driver=self.ec2, created_at=instance['LaunchTime'], extra=None)
        return node, {
            'groupId': temp_security_group,
            'vpcId': subnet['VpcId'],
        }


    def get_node(self, node):
        if isinstance(node, str):
            instance_response = self.ec2.describe_instances(Filters=[{
                'Name': 'tag:Name',
                'Values': [node],
            }])
        else:
            # This can fail if called right after run_instances, retry if not found
            start_time = time.time()
            exception = None
            while time.time() - start_time < 20:
                try:
                    instance_response = self.ec2.describe_instances(InstanceIds=[node.id])
                    break
                except Exception as error:
                    exception = error
                    time.sleep(1)
            else:
                # no break
                raise ValueError('Instance not found') from exception

        instance = instance_response['Reservations'][0]['Instances'][0]
        public_ip = instance.get('PublicIpAddress')
        public_ips = [public_ip] if public_ip else []
        name = None
        for tag in instance['Tags']:
            if tag['Key'] == 'Name':
                name = tag['Value']
                break
        private_ip = instance.get('PrivateIpAddress')
        private_ips = [private_ip] if private_ip else []
        return Node(id=instance['InstanceId'], name=name, state=instance['State']['Name'],
            public_ips=public_ips, private_ips=private_ips, driver=self.ec2,
            created_at=instance['LaunchTime'], extra=None)


    def create_temp_security_group(self, minion_id, connection_gateway, vpc_id):
        current_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
        name = 'temp-for-%s-%s' % (minion_id, current_date)

        # Get the external IPs for the current host to let through the firewall
        # to the minion for the initial ssh connection
        if connection_gateway:
            external_ips = [connection_gateway]
        else:
            external_ips = list(get_host_public_ips())

        if not external_ips:
            raise UserError('Could not find any public IPs on the current '
                'host and thus wont be able to connect to the new node')

        group = self.ec2.create_security_group(
            GroupName=name,
            Description='Temporary group for initial saltmaster ssh initialization',
            VpcId=vpc_id,
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
        # The release process for the official debian images changed a bit from
        # buster and onwards. The owner account changed, and the images changed
        # from being named debian-<codename>.. to debian-<version>..
        debian_version = DEBIAN_VERSIONS[debian_codename]
        is_buster_or_newer = debian_version >= 10
        official_debian_account = '136693071363' if is_buster_or_newer else '379101102735'
        image_response = self.ec2.describe_images(Owners=[official_debian_account], Filters=[{
            'Name': 'architecture',
            'Values': ['x86_64'],
        }])
        image_prefix = 'debian-%s' % (debian_version if is_buster_or_newer else debian_codename)
        dist_images = [i for i in image_response['Images'] if i['Name'].startswith(image_prefix)]
        dist_images.sort(key=lambda i: i['Name'])
        return dist_images[-1]


    def post_connect(self, hart_node):
        # Delete the temp security group that allowed ssh
        # Detach the security group from the instance. An instance must have at
        # least one security group, so we attach the VPC default group.
        self.delete_node_security_group(
            hart_node.node,
            hart_node.node_extra['groupId'],
            hart_node.node_extra['vpcId'],
        )


    def delete_node_security_group(self, node, group_id, vpc_id):
        response = self.ec2.describe_security_groups(
            Filters=[{
                'Name': 'group-name',
                'Values': ['default'],
            }, {
                'Name': 'vpc-id',
                'Values': [vpc_id],
            }],
        )
        default_group = response['SecurityGroups'][0]
        self.ec2.modify_instance_attribute(InstanceId=node.id, Groups=[default_group['GroupId']])
        print('Deleting temporary security group')
        response = self.ec2.delete_security_group(GroupId=group_id)


    def destroy_node(self, node, extra=None, **kwargs):
        if extra is not None:
            self.delete_node_security_group(node, extra['groupId'], extra['vpcId'])

        self.ec2.terminate_instances(InstanceIds=[node.id])


    def get_size(self, size_name):
        return size_name


    def get_sizes(self, **kwargs):
        region = self.region
        if region is None:
            sys.stderr.write('No region specified, using us-east-1. Sizes listed might not exist '
                'in any other region\n')
            region = 'us-east-1'

        pricing = boto3.client('pricing',
            region_name='us-east-1',
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )
        sizes = []
        location = region_to_location_map[region]
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


    def get_regions(self, include_zones=False, **kwargs):
        regions = []
        # If not region is specified, pick an arbitrary one that is probably
        # active (ie added before March 20, 2019)
        if not self.region:
            self.region = 'us-west-1'

        response = self.ec2.describe_regions()
        for region in response['Regions']:
            if include_zones:
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
            else:
                region_id = region['RegionName']
                name = region_to_location_map.get(region_id, 'Unknown')
                regions.append(Region(region_id, name))
        regions.sort(key=lambda r: r.name)
        return regions


def get_host_public_ips():
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            string_ip = ip.ip[0] if isinstance(ip.ip, tuple) else ip.ip
            address = ipaddress.ip_address(string_ip)
            if address.is_global:
                yield '%s/%s' % (string_ip, address.max_prefixlen)
