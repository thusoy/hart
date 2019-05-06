import os

import toml

from .providers import provider_map


def build_provider_from_file(provider_alias, config_file='~/.hartrc', **kwargs):
    constructor = provider_map[provider_alias]
    file_path = os.path.expanduser(config_file)
    with open(file_path) as fh:
        config = toml.load(fh)

    provider_config = config['providers'][provider_alias]
    return constructor(**provider_config, **kwargs)
