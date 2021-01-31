import binascii
import os

from .config import load_config
from .exceptions import UserError

DEFAULT_ROLE_NAMING_SCHEME = '{unique_id}.{region}.{provider}.{role}'

def get_minion_arguments_for_role(config_file, role, provider=None):
    config = load_config(config_file)
    core_config = config.get('hart', {})
    role_config = config.get('roles', {}).get(role)
    if role_config is None:
        raise UserError('Unknown role %r, must be one of %s' % (
            role, ', '.join(repr(r) for r in config.get('roles', {}))))

    role_provider_config = role_config.get(provider, {})
    merged_config = {}
    merged_config.update(core_config)
    merged_config.update(role_config)
    merged_config.update(role_provider_config)

    minion_config = {
        # Default to keep retrying a master connection if it fails
        'master_tries': -1,
        'grains': {
            'roles': [role],
        },
    }
    saltmaster = core_config.get('saltmaster')
    if saltmaster:
        minion_config['master'] = saltmaster

    if provider is None:
        provider = merged_config.get('provider')

    kwargs = {}
    salt_branch = merged_config.get('salt_branch')
    if salt_branch:
        kwargs['salt_branch'] = salt_branch

    return {
        'minion_id': build_minion_id(core_config.get('role_naming_scheme', DEFAULT_ROLE_NAMING_SCHEME),
            role=role,
            region=merged_config.get('region'),
            provider=provider,
        ),
        'private_networking': merged_config.get('private_networking', False),
        'provider': provider,
        'region': merged_config.get('region'),
        'size': merged_config.get('size'),
        'minion_config': minion_config,
        **kwargs,
    }


def build_minion_id(naming_scheme, **kwargs):
    kwargs['unique_id'] = get_unique_id()
    try:
        return naming_scheme.format(**kwargs)
    except KeyError as error:
        raise UserError('Invalid minion id template variable {%s}, must be one of %s' % (
            error.args[0], ', '.join('{%s}' % s for s in sorted(kwargs))))


def get_unique_id():
    return binascii.hexlify(os.urandom(4)).decode('utf-8')
