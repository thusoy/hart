import binascii
import datetime
import os

from .config import load_config, build_provider_from_config
from .exceptions import UserError

DEFAULT_MINION_NAMING_SCHEME = '{unique_id}.{region}.{provider}.{role}'

def get_minion_arguments_for_role(config_file, role, provider=None, region=None):
    config = load_config(config_file)
    core_config = config.get('hart', {})
    role_config = config.get('roles', {}).get(role)
    if role_config is None:
        roles = config.get('roles', {})
        if roles:
            raise UserError('Unknown role %r, must be one of %s' % (
                role, ', '.join(repr(r) for r in config.get('roles', {}))))
        else:
            raise UserError('Unknown role %r, no roles defined in config' % role)

    merged_config = {}
    merged_config.update(core_config)

    if region is None:
        region = merged_config.pop('region', None)

    if provider is None:
        provider_alias = merged_config.pop('provider', role_config.pop('provider', None))
        provider = build_provider_from_config(provider_alias, config, region=region)

    provider_config = role_config.pop(provider.alias, {})
    merged_config.update(role_config)

    region_config = provider_config.pop(region, {})
    merged_config.update(provider_config)
    merged_config.update(region_config)

    # We might not know the region until getting the provider config, thus try
    # to get it again
    if region is None:
        region = merged_config.pop('region')

    default_minion_config = {
        # Default to keep retrying a master connection if it fails
        'master_tries': -1,
        'grains': {
            'roles': [role],
        },
    }

    saltmaster = merged_config.pop('saltmaster', None)
    if saltmaster:
        default_minion_config['master'] = saltmaster

    minion_config = merged_config.pop('minion_config', {})
    if minion_config:
        merge_dicts(default_minion_config, minion_config)

    kwargs = merged_config

    salt_branch = merged_config.get('salt_branch')
    if salt_branch:
        kwargs['salt_branch'] = salt_branch

    size = merged_config.get('size')
    if size:
        kwargs['size'] = size

    naming_scheme = merged_config.pop('role_naming_scheme', DEFAULT_MINION_NAMING_SCHEME)

    return {
        'minion_id': build_minion_id(naming_scheme,
            role=role,
            region=region,
            provider=provider.alias,
        ),
        'provider': provider,
        'region': region,
        'minion_config': default_minion_config,
        **kwargs,
    }


def build_minion_id(naming_scheme, **kwargs):
    now = datetime.datetime.utcnow()
    kwargs['unique_id'] = get_unique_id()
    kwargs['year'] = now.strftime('%Y')
    kwargs['month'] = now.strftime('%m')
    kwargs['day'] = now.strftime('%d')
    try:
        return naming_scheme.format(**kwargs)
    except KeyError as error:
        raise UserError('Invalid minion id template variable {%s}, must be one of %s' % (
            error.args[0], ', '.join('{%s}' % s for s in sorted(kwargs))))


def merge_dicts(a, b):
    # b overwrites leaf values in a
    for key, val in b.items():
        if isinstance(val, dict):
            a[key] = merge_dicts(a[key], val)
        else:
            a[key] = val
    return a


def get_unique_id():
    return binascii.hexlify(os.urandom(4)).decode('utf-8')
