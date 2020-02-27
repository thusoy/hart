import hashlib
import re

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
    'asia-southeast1': 'Jurong West, Singapore',
    'australia-southeast1': 'Sydney, Australia',
    'europe-north1': 'Hamina, Finland',
    'europe-west1': 'St. Ghislain, Belgium',
    'europe-west2': 'London, England, UK',
    'europe-west3': 'Frankfurt, Germany',
    'europe-west4': 'Eemshaven, Netherlands',
    'europe-west6': 'Zürich, Switzerland',
    'northamerica-northeast1': 'Montréal, Québec, Canada',
    'southamerica-east1': 'Osasco (São Paulo), Brazil',
    'us-central1': 'Council Bluffs, Iowa, USA',
    'us-east1': 'Moncks Corner, South Carolina, USA',
    'us-east4': 'Ashburn, Northern Virginia, USA',
    'us-west1': 'The Dalles, Oregon, USA',
    'us-west2': 'Los Angeles, California, USA',
}


class GCEProvider(BaseLibcloudProvider):

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
        parser.add_argument('--volume-size', type=int, default=10,
            help='The size of the boot drive in GB, minimum 10')
        parser.add_argument('--volume-type', default='pd-ssd',
            help='Which volume type to use for the boot drive. Default: %(default)s',
            choices=('pd-standard', 'pd-ssd'))
        # To use the highest-performing disk on GCE (local ssd mounted over
        # NVMe) we need to mount multiple disks as that can't be the boot disk.
        # Decide on a CLI convention for specifying arbitrary additional disks.
        # Ref. https://cloud.google.com/compute/docs/disks/#introduction


    def create_node(self,
            minion_id,
            region,
            debian_codename,
            auth_key,
            cloud_init,
            private_networking,
            tags,
            size='n1-standard-1',
            **kwargs):
        zone = kwargs.get('zone')
        if not zone:
            raise UserError('You must specify the GCE zone to launch in')

        zone = self.driver.ex_get_zone(zone)
        image = self.driver.ex_get_image('debian-%d' % DEBIAN_VERSIONS[debian_codename])
        volume_type = kwargs.get('volume_type')
        disk_type = self.driver.ex_get_disktype(volume_type, zone=zone)
        node = self.driver.create_node(
            name=name_from_minion_id(minion_id),
            size=size,
            location=zone,
            image=None, # Specified in the disk params
            description=minion_id,
            ex_tags=tags,
            ex_metadata={
                'sshKeys': auth_key,
                'startup-script': cloud_init,
            },
            ex_labels=kwargs.get('labels'),
            ex_disks_gce_struct=[{
                'autoDelete': True,
                'boot': True,
                'type': 'PERSISTENT', # The boot drive has to be persistent
                'mode': 'READ_WRITE',
                'initializeParams': {
                    'diskSizeGb': kwargs.get('volume_size'),
                    'diskType': disk_type.extra['selfLink'],
                    'sourceImage': image.extra['selfLink']
                }
            }],
        )
        return node, None


    def wait_for_init_script(self, client, extra=None):
        # Creds to https://stackoverflow.com/a/14158100 for a way to get the pid
        _, stdout, _ = client.exec_command(
            'echo $$ && exec tail -f -n +1 /var/log/syslog')
        tail_pid = int(stdout.readline())
        startup_script_end = re.compile(r'startup-script: Return code (\d+)\.\n$', re.MULTILINE)
        for line in stdout:
            print(line, end='')
            end_match = startup_script_end.search(line)
            if end_match:
                stdout.channel.close()
                client.exec_command('kill %d' % tail_pid)
                return_code = int(end_match.group(1))
                if return_code == 0:
                    break

                raise ValueError('Startup script failed with return code %s' % return_code)


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
    sanitized_name = minion_id.replace('.', '-')
    hashed_id = hashlib.sha256(minion_id.encode('utf-8')).hexdigest()
    return 'hart-%s-%s' % (sanitized_name[:47], hashed_id[:10])
