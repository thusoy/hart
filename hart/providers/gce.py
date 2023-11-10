import hashlib

from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider

from .base import NodeSize, Region
from .libcloud import BaseLibcloudProvider
from ..constants import DEBIAN_VERSIONS
from ..exceptions import UserError

# Haven't found a way to get pretty location names from the API yet, thus
# hardcoding these where we know them
region_pretty_names = {
    'asia-east1': 'Changhua County, Taiwan',
    'asia-east2': 'Hong Kong',
    'asia-northeast1': 'Tokyo, Japan',
    'asia-northeast2': 'Osaka, Japan',
    'asia-northeast3': 'Seoul, South Korea',
    'asia-south1': 'Mumbai, India',
    'asia-south2': 'Delhi, India',
    'asia-southeast1': 'Jurong West, Singapore',
    'asia-southeast2': 'Jakarta, Indonesia',
    'australia-southeast1': 'Sydney, Australia',
    'australia-southeast2': 'Melbourne, Australia',
    'europe-central2': 'Warsaw, Poland',
    'europe-north1': 'Hamina, Finland',
    'europe-west1': 'St. Ghislain, Belgium',
    'europe-west2': 'London, England, UK',
    'europe-west3': 'Frankfurt, Germany',
    'europe-west4': 'Eemshaven, Netherlands',
    'europe-west6': 'Zürich, Switzerland',
    'northamerica-northeast1': 'Montréal, Québec, Canada',
    'northamerica-northeast2': 'Toronto, Ontario',
    'southamerica-east1': 'Osasco (São Paulo), Brazil',
    'us-central1': 'Council Bluffs, Iowa, USA',
    'us-east1': 'Moncks Corner, South Carolina, USA',
    'us-east4': 'Ashburn, Northern Virginia, USA',
    'us-west1': 'The Dalles, Oregon, USA',
    'us-west2': 'Los Angeles, California, USA',
    'us-west3': 'Salt Lake City, Utah, USA',
    'us-west4': 'Las Vegas, Nevada, USA',
}


class GCEProvider(BaseLibcloudProvider):
    alias = 'gce'
    default_size = 'n1-standard-1'

    def __init__(self, user_id, key, project, region=None, **kwargs):
        constructor = get_driver(Provider.GCE)
        self.driver = constructor(user_id=user_id, key=key, project=project, auth_type='SA')
        self.region = region


    def get_sizes(self, **kwargs):
        sizes = []
        # TODO: Integrate with pricing API, these will be estimates based on 2020-01-31 Iowa pricing
        cpu_cost = 16.153221
        memory_cost = 2.165107
        for size in self.driver.list_sizes(self.region or 'us-east1-b'):
            sizes.append(NodeSize(
                size.name,
                size.ram/2**10,
                size.extra['guestCpus'],
                'No disk', # Extra volumes beyond the tiny root disk needs to be specified manually
                size.ram/2**10 * memory_cost + size.extra['guestCpus'] * cpu_cost,
                {},
            ))

        sizes.sort(key=lambda s: s.monthly_cost)
        return sizes


    def add_list_regions_arguments(self, parser):
        parser.add_argument('-z', '--include-zones', action='store_true')


    def get_regions(self, include_zones=False, **kwargs):
        regions = []
        for location in self.driver.ex_list_regions():
            pretty_name = region_pretty_names.get(location.name, location.name)
            if include_zones:
                for zone in location.zones:
                    regions.append(Region(zone.name, pretty_name))
            else:
                regions.append(Region(location.name, pretty_name))
        regions.sort(key=lambda r: r.id)
        return regions


    def create_remote_ssh_key(self, key_name, ssh_key, public_key):
        # Since we don't use global keys there's no item on GCE to represent the key
        return (key_name, 'root:%s hart@saltmaster' % public_key)


    def destroy_remote_ssh_key(self, remote_key):
        # The saltmaster discards the key after creation so don't have to remove it from the
        # metadata apart from cleaning up
        pass


    def add_create_minion_arguments(self, parser):
        def split_csv_keyval(clistring):
            ret = {}
            for key_value_pair in clistring.split(','):
                if not '=' in key_value_pair:
                    raise UserError('GCE requires labels to be key=value pairs')

                key, value = key_value_pair.split('=', 1)
                ret[key] = value
            return ret

        parser.add_argument('-z', '--zone', help='GCE zone to launch in')
        parser.add_argument('-l', '--labels', type=split_csv_keyval,
            help='Comma-separated key=value pairs of labels to add to the node.')
        parser.add_argument('--subnet', help='The subnet to launch in.')
        parser.add_argument('--volume-size', type=int, default=10,
            help='The size of the boot drive in GB, minimum 10')
        parser.add_argument('--volume-type', default='pd-ssd',
            help='Which volume type to use for the boot drive. Default: %(default)s',
            choices=('pd-standard', 'pd-ssd'))
        parser.add_argument('--enable-oslogin', action='store_true',
            help='By default OS Login is disabled, pass this flag to enable it for this minion')
        parser.add_argument('--local-ssds', type=int, default=0,
            help='How many local ssds to attach (using NVMe). The disks will not be '
            'formatted or mounted, this needs to be done outside of hart (f. ex in an '
            'init script, or from salt)')


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

        desired_zone = kwargs.get('zone')
        if not desired_zone:
            raise UserError('You must specify the GCE zone to launch in')

        zone = self.driver.ex_get_zone(desired_zone)
        if not zone:
            raise UserError('Unknown zone %r' % desired_zone)

        subnet_string = kwargs.get('subnet')
        # The arm image looks like
        # debian-<debian-numeric-version>-<debian-codename>-arm64-v20231010
        # The x86-64 image looks like
        # debian-<debian-numeric-version>-<debian-codename>-v20231010
        # To avoid getting the wrong arch on the image we need to include enough
        # of the prefix to identify the image uniquely
        image = self.driver.ex_get_image('debian-%d-%s-v' % (
            DEBIAN_VERSIONS[debian_codename], debian_codename))
        volume_type = kwargs.get('volume_type')
        disk_type = self.driver.ex_get_disktype(volume_type, zone=zone)
        regional_subnets = self.driver.ex_list_subnetworks(region)
        subnet = get_selected_or_default_subnet(regional_subnets, subnet_string)
        disks = [{
            'autoDelete': True,
            'boot': True,
            'type': 'PERSISTENT', # The boot drive has to be persistent
            'mode': 'READ_WRITE',
            'initializeParams': {
                'diskSizeGb': kwargs.get('volume_size'),
                'diskType': disk_type.extra['selfLink'],
                'sourceImage': image.extra['selfLink']
            }
        }]
        local_ssd = kwargs.get('local_ssds', 0)
        for i in range(local_ssd):
            disks.append({
                'autoDelete': True,
                'type': 'SCRATCH',
                'interface': 'NVME',
                'initializeParams': {
                    'diskType': f'zones/{desired_zone}/diskTypes/local-ssd',
                }
            })
        node = self.driver.create_node(
            name=name_from_minion_id(minion_id),
            size=size,
            location=zone,
            image=None, # Specified in the disk params
            description=minion_id,
            ex_tags=tags,
            ex_network=subnet.network,
            ex_subnetwork=subnet,
            ex_metadata={
                'sshKeys': auth_key,
                'startup-script': cloud_init,
                # We assume that if you manage servers with salt you want to use salt to
                # manage ssh access, but we allow this to be overridden
                'enable-oslogin': kwargs.get('enable_oslogin', False),
            },
            ex_labels=kwargs.get('labels'),
            ex_disks_gce_struct=disks,
        )
        return node, None


    def wait_for_init_script(self, client, extra=None):
        # Creds to https://stackoverflow.com/a/14158100 for a way to get the pid
        _, stdout, _ = client.exec_command(
            'echo $$ && exec tail -f -n +1 /var/log/syslog')
        tail_pid = int(stdout.readline())
        for line in stdout:
            print(line, end='')
            # TODO: This doesn't detect if the init script failed for some reason, need
            # to find a reliable way to do that
            if 'hart-init-complete' in line:
                stdout.channel.close()
                client.exec_command('kill %d' % tail_pid)
                break


    def destroy_node(self, node, extra=None, **kwargs):
        self.driver.destroy_node(node, ex_sync=False)


    def get_node(self, node):
        if isinstance(node, str):
            node = self.driver.ex_get_node(name_from_minion_id(node))
        else:
            node = self.driver.ex_get_node(node.name)
        return node


def name_from_minion_id(minion_id):
    '''
    Transform a minion id into a valid GCE VM name.

    GCE VM names has to be a valid DNS label, which doesn't allow dots, or
    leading numbers. Thus we transform minion ids into a compatible name which
    is preferably also somewhat legible from the cloud console. The full minion
    id is stored in the description. This also needs to be deterministic.
    '''
    sanitized_name = '-'.join(reversed(minion_id.split('.')))
    hashed_id = hashlib.sha256(minion_id.encode('utf-8')).hexdigest()
    return 'hart-%s-%s' % (sanitized_name[:47], hashed_id[:6])


def get_selected_or_default_subnet(subnets, subnet_string):
    if not subnets:
        raise UserError('No subnets available in the given region')

    if subnet_string is None and len(subnets) == 1:
        return subnets[0]
    elif subnet_string is None:
        raise UserError('More than one subnet available in %s, need to pick one of %s' % (
            subnets[0].region.name, ', '.join(s.name for s in subnets)))

    for subnet in subnets:
        if subnet.name == subnet_string:
            return subnet

    raise UserError('None of the subnets in %s match %r, should be one of %s' % (
        subnets[0].region.name, subnet_string, ', '.join(s.name for s in subnets)))
