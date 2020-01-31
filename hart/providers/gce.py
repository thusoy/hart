import contextlib
import datetime
import json
import time
import subprocess

from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider, NodeState
from libcloud.utils.py3 import httplib

from .base import NodeSize, Region
from .libcloud import BaseLibcloudProvider

# Haven't found a way to get pretty location names from the API yet, thus hardcoding these where we know them
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
