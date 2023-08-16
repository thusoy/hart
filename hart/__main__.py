import argparse
import json
import sys

from .config import build_provider_from_file
from .constants import DEBIAN_VERSIONS
from .exceptions import UserError
from .minions import (
    create_minion,
    destroy_minion,
)
from .master import create_master
from .providers import provider_map
from .roles import get_minion_arguments_for_role, get_provider_for_role
from .utils import log_error, log_warning
from .version import __version__


def main(argv=None):
    try:
        cli = HartCLI()
        args = cli.get_args(argv)
        args.action(args)
    except UserError as error:
        log_error(str(error))
        sys.exit(1)


class DefaultArgumentString(str):
    # If this is used for default values in argparse we can detect when a
    # default is being used vs being set explicitly
    pass


class HartCLI:
    def __init__(self):
        if sys.getfilesystemencoding() == 'ascii':
            raise UserError('Your system has incorrect locale settings, '
                'leading to non-unicode default IO. Set f. ex '
                'LC_CTYPE=en_US.UTF-8 and PYTHONIOENCODING=utf-8 to fix this.')


    def get_args(self, argv):
        # Define a conflict handler to let subclasses override defaults
        parser = argparse.ArgumentParser(prog='hart', add_help=False, conflict_handler='resolve')

        parser.add_argument('-P', '--provider', choices=provider_map.keys(),
            help='Which VPS provider to use.')
        parser.add_argument('-R', '--region',
            help='Which region to create the node in.')
        parser.add_argument('-c', '--config', default='/etc/hart.toml',
            help='Path to config file with credentails. Default: %(default)s')
        # Explicitly add help to be able to parse the provider before printing the help
        parser.add_argument('-h', '--help', action='store_true', help='Print help')
        parser.add_argument('-v', '--version', action='version', version='hart v%s' % __version__)

        subparsers = parser.add_subparsers(dest='command',
            title='Commands',
            help='What do you want to do?')

        create_minion_from_role_parser = self.add_create_minion_from_role_parser(subparsers)
        create_minion_parser = self.add_create_minion_parser(subparsers)
        create_master_parser = self.add_create_master_parser(subparsers)
        destroy_minion_parser = self.add_destroy_minion_parser(subparsers)
        list_regions_parser = self.add_list_regions_parser(subparsers)
        list_sizes_parser = self.add_list_sizes_parser(subparsers)

        # Do an initial parse of just the provider arguments, to be able to add
        # provider-specific arguments to the full parse. If a provider is given
        # on the command line that takes precedence, otherwise when creating
        # from a role there might be a provider specified in the config file,
        # use that.
        provider_args, _ = parser.parse_known_args(argv)
        provider = None

        try:
            if provider_args.provider:
                provider = get_provider(provider_args.provider, provider_args.config,
                    provider_args.region)
            elif provider_args.command == 'create-minion-from-role':
                provider = get_provider_for_role(
                    provider_args.config, provider_args.role, provider_args.region)
            else:
                raise UserError('No provider specified')

        except (FileNotFoundError, KeyError):
            # Enable running help without having a valid provider config
            # FileNotFoundError if config is missing entirely, KeyError if the
            # defualt or given provider is missing
            # TODO: This ignores any action that might be given, the defualt
            # parameters for those should be included
            if provider_args.help:
                log_warning('Unable to instantiate provider, add a valid provider config to see '
                    'all available parameters')
                parser.print_help()
                sys.exit(0)
            raise

        # Add the same arguments to create-minion-from-role as create-minion
        provider.add_create_minion_arguments(create_minion_from_role_parser)
        provider.add_create_minion_arguments(create_minion_parser)
        provider.add_create_minion_arguments(create_master_parser)
        provider.add_destroy_minion_arguments(destroy_minion_parser)
        provider.add_list_regions_arguments(list_regions_parser)
        provider.add_list_sizes_arguments(list_sizes_parser)

        args = parser.parse_args(argv)
        args.provider = provider

        if args.help:
            parser.print_help()
            sys.exit(0)

        if not getattr(args, 'action', None):
            parser.print_help()
            sys.exit(1)

        return args


    def add_create_minion_from_role_parser(self, subparsers):
        parser = subparsers.add_parser('create-minion-from-role', help='Create a new minion with a given role')
        parser.add_argument('role', help='Name of the role')
        self._add_minion_master_role_shared_arguments(parser)
        parser.set_defaults(action=self.create_cli_create_minion_from_role(parser))
        return parser


    def add_create_minion_parser(self, subparsers):
        parser = subparsers.add_parser('create-minion', help='Create a new minion')
        parser.add_argument('minion_id')
        self._add_minion_master_role_shared_arguments(parser)
        parser.set_defaults(action=self.cli_create_minion)
        return parser


    def add_create_master_parser(self, subparsers):
        parser = subparsers.add_parser('create-master', help='Create a new saltmaster')
        parser.add_argument('minion_id')
        self._add_minion_master_role_shared_arguments(parser)

        parser.add_argument('-a', '--authorize-key',
            help='An ssh public key to add to .ssh/authorized_keys.')
        parser.add_argument('-g', '--grains', type=type_json,
            help="Grains to write to /etc/salt/minion.d/grains.conf")

        parser.set_defaults(action=self.cli_create_master)
        return parser


    def _add_minion_master_role_shared_arguments(self, parser): # pylint disable=no-self-use
        def type_csv(clistring):
            return clistring.split(',')

        parser.add_argument('-s', '--size',
            help='The size of the node to create. Default varies with provider.')
        parser.add_argument('-t', '--tags', type=type_csv, default=[],
            help='Tags to add to the new node, comma-separated.')
        parser.add_argument('-S', '--script', help='Path to a script to run on '
            'the master after salt has been installed. Use this to customize '
            'your setup and deploy any secrets you might need.')
        parser.add_argument('-p', '--private-networking', action='store_true',
            help='Whether to enable private networking on the node')
        parser.add_argument('-d', '--debian-codename',
            choices=DEBIAN_VERSIONS.keys(), default=DefaultArgumentString('bookworm'),
            help='Which debian version to create. Default: %(default)s')
        parser.add_argument('--use-py2', action='store_true',
            help='Use py2 instead of py3 for saltstack.')
        parser.add_argument('--salt-branch', default=DefaultArgumentString('latest'),
            help='The salt branch to use. Default: %(default)s')
        parser.add_argument('--minion-config', type=type_json,
            help='Minion config in JSON')


    def add_destroy_minion_parser(self, subparsers):
        parser = subparsers.add_parser('destroy-minion', help='Destroy a minion')
        parser.add_argument('minion_id')

        parser.set_defaults(action=self.cli_destroy_minion)
        return parser


    def add_list_regions_parser(self, subparsers):
        parser = subparsers.add_parser('list-regions',
            help='List available regions for a provider')

        parser.set_defaults(action=self.cli_list_regions)
        return parser


    def add_list_sizes_parser(self, subparsers):
        parser = subparsers.add_parser('list-sizes',
            help='List available sizes in a region for a provider')

        parser.set_defaults(action=self.cli_list_sizes)
        return parser


    def create_cli_create_minion_from_role(self, parser):
        def cli_create_minion_from_role(args):
            cli_kwargs = {}
            for key, val in vars(args).items():
                if key in ('provider', 'role'):
                    continue
                if val is not parser.get_default(key):
                    cli_kwargs[key] = val

            kwargs = get_minion_arguments_for_role(
                args.config, args.role, args.provider, args.region, cli_kwargs)
            for key, val in kwargs.items():
                setattr(args, key, val)
            self.cli_create_minion(args)
        return cli_create_minion_from_role


    def cli_create_minion(self, args):
        kwargs = vars(args)
        try:
            create_minion(**kwargs)
        except KeyboardInterrupt:
            print('Aborted by Ctrl-C or SIGINT, stopping')


    def cli_create_master(self, args):
        kwargs = vars(args)
        try:
            create_master(**kwargs)
        except KeyboardInterrupt:
            print('Aborted by Ctrl-C or SIGINT, stopping')


    def cli_destroy_minion(self, args):
        kwargs = vars(args)
        provider = kwargs.pop('provider')
        minion_id = kwargs.pop('minion_id')
        destroy_minion(minion_id, provider, **kwargs)


    def cli_list_sizes(self, args):
        kwargs = vars(args)
        provider = kwargs.pop('provider')
        for size in provider.get_sizes(**kwargs):
            formatted_memory = '%d' % size.memory if size.memory >= 1 else '%.1f' % size.memory
            print('%d vCPUs, %s GB RAM, %s (%s, $%d/month) %s' % (
                size.cpu,
                formatted_memory,
                size.disk,
                size.id,
                size.monthly_cost,
                size.extras or ''),
            )


    def cli_list_regions(self, args):
        kwargs = vars(args)
        provider = kwargs.pop('provider')
        for location in provider.get_regions(**kwargs):
            print('%s (%s)' % (location.name, location.id))


def type_json(value):
    return json.loads(value)


def get_clean_kwargs_from_args(args):
    kwargs = vars(args)
    del kwargs['provider']
    return kwargs


def get_provider(provider_alias, config_path, region):
    return build_provider_from_file(provider_alias, config_path, region=region)


if __name__ == '__main__':
    main(sys.argv)
