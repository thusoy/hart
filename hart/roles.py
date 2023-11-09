import binascii
import datetime
import os

from .config import load_config, build_provider_from_config
from .exceptions import UserError

DEFAULT_MINION_NAMING_SCHEME = '{unique_id}.{region}.{provider}.{role}'

def get_provider_for_role(config_file, role, region):
    config = load_config(config_file)
    core_config = config.get('hart', {})
    role_config = get_role_config(config, role)

    merged_config = {}
    merged_config.update(core_config)

    if region is None:
        region = merged_config.pop('region', None)

    provider_alias = merged_config.pop('provider', role_config.pop('provider', None))
    return build_provider_from_config(provider_alias, config, region=region)


def get_minion_arguments_for_role(config_file, role, provider=None, region=None, cli_kwargs=None):
    if cli_kwargs is None:
        cli_kwargs = {}

    config = load_config(config_file)
    core_config = config.get('hart', {})
    role_config = get_role_config(config, role)

    merged_config = {}
    merged_config.update(core_config)

    if region is None:
        region = merged_config.pop('region', None)

    provider_alias = merged_config.pop('provider', role_config.pop('provider', None))
    if provider is None:
        provider = build_provider_from_config(provider_alias, config, region=region)

    provider_config = role_config.pop(provider.alias, {})
    merged_config.update(role_config)

    region_config = provider_config.pop(region, {})
    merged_config.update(provider_config)
    merged_config.update(region_config)
    merged_config.update(cli_kwargs)

    # We might not know the region until getting the provider config, thus try
    # to get it again
    if region is None:
        region = merged_config.pop('region')
    else:
        merged_config.pop('region', None)

    size = merged_config.setdefault('size', provider.default_size)

    default_minion_config = {
        'grains': {
            'roles': [role],
            'hart.region': region,
            'hart.provider': provider.alias,
            'hart.size': size,
        },
        # Default to keep retrying a master connection if it fails
        'master_tries': -1,
        # This config is necessary to make salt try to reconnect to a master on
        # a new IP in case of failover
        'master_alive_interval': 90,
        'auth_safemode': False,
        'master_type': 'failover',
        'retry_dns': 0,
    }

    saltmaster = merged_config.pop('saltmaster', None)
    if saltmaster:
        default_minion_config['master'] = saltmaster

    minion_config = merged_config.pop('minion_config', {})
    if minion_config:
        merge_dicts(default_minion_config, minion_config)

    naming_scheme = merged_config.pop('role_naming_scheme', DEFAULT_MINION_NAMING_SCHEME)

    # Prevent duplicate provider error, added back again soon
    merged_config.pop('provider', None)

    merged_config['minion_id'] = build_minion_id(naming_scheme,
        role=role,
        region=region,
        provider=provider.alias,
        **merged_config,
    )
    merged_config['provider'] = provider
    merged_config['region'] = region
    merged_config['minion_config'] = default_minion_config

    if provider.alias == 'gce':
        merged_config.setdefault('labels', {}).update({
            'hart-role': role,
        })

    return merged_config


def get_role_config(config, role):
    roles = config.get('roles', {})
    role_config = roles.get(role)
    if role_config is None:
        if roles:
            raise UserError('Unknown role %r, must be one of %s' % (
                role, ', '.join(repr(r) for r in config.get('roles', {}))))
        else:
            raise UserError('Unknown role %r, no roles defined in config' % role)
    return role_config


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
