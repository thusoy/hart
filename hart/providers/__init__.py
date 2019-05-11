from .digitalocean import DOProvider
from .ec2 import EC2Provider
from .vultr import VultrProvider

provider_map = {
    'do': DOProvider,
    'ec2': EC2Provider,
    'vultr': VultrProvider,
}
