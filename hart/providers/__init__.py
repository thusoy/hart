from .digitalocean import DOProvider
from .ec2 import EC2Provider
from .vultr import VultrProvider
from .gce import GCEProvider

provider_map = {}
for provider in (
        DOProvider,
        EC2Provider,
        VultrProvider,
        GCEProvider):
    provider_map[provider.alias] = provider
