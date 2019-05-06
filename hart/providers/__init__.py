from .digitalocean import DOProvider
from .ec2 import EC2Provider

provider_map = {
    'do': DOProvider,
    'ec2': EC2Provider,
}
