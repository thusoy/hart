import argparse
import sys

from .config import build_provider_from_file
from .constants import DEBIAN_VERSIONS
from .minions import (
    create_minion,
    connect_minion,
    destroy_minion,
    destroy_node,
)
from .providers import provider_map

def main():
    cli = HartCLI()
    args = cli.get_args()
    args.action(args)


class HartCLI:
    def __init__(self):
        if sys.getfilesystemencoding() == 'ascii':
            raise ValueError('Your system has incorrect locale settings, '
                'leading to non-unicode default IO. Set f. ex '
                'LC_CTYPE=en_US.UTF-8 and PYTHONIOENCODING=utf-8 to fix this.')


    def get_args(self):
        parser = argparse.ArgumentParser(prog='hart', add_help=False)

        parser.add_argument('-P', '--provider', choices=provider_map.keys(), default='do',
            help='Which VPS provider to use. Default: %(default)s')
        parser.add_argument('--region',
            help='Which region to create the node in. Default: %(default)s')
        parser.add_argument('-c', '--config', default='/etc/hart.toml',
            help='Path to config file with credentails. Default: %(default)s')
        # Explicitly add help to be able to parse the provider before printing the help
        parser.add_argument('-h', '--help', action='store_true', help='Print help')

        # Do an initial parse of just the provider arguments, to be able to add
        # provider-specific arguments to the full parse
        provider_args, _ = parser.parse_known_args()
        provider = get_provider(provider_args.provider, provider_args.config,
            provider_args.region)

        subparsers = parser.add_subparsers(dest='command',
            title='Commands',
            help='What do you want to do?')

        create_minion_parser = self.add_create_minion_parser(subparsers)
        destroy_minion_parser = self.add_destroy_minion_parser(subparsers)
        list_regions_parser = self.add_list_regions_parser(subparsers)
        list_sizes_parser = self.add_list_sizes_parser(subparsers)

        provider.add_create_minion_arguments(create_minion_parser)
        provider.add_destroy_minion_arguments(destroy_minion_parser)
        provider.add_list_regions_arguments(list_regions_parser)
        provider.add_list_sizes_arguments(list_sizes_parser)

        args = parser.parse_args()
        args.provider = provider

        if args.help:
            parser.print_help()
            sys.exit(0)

        if not getattr(args, 'action', None):
            parser.print_help()
            sys.exit(1)

        return args


    def add_create_minion_parser(self, subparsers):
        def split_csv(clistring):
            return clistring.split(',')

        parser = subparsers.add_parser('create-minion', help='Create a new minion')
        parser.add_argument('minion_id')
        parser.add_argument('-s', '--size',
            help='The size of the node to create. Default varies with provider.')
        parser.add_argument('-t', '--tags', type=split_csv, default=[],
            help='Tags to add to the new node, comma-separated.')
        parser.add_argument('-p', '--private-networking', action='store_true',
            help='Whether to enable private networking on the node')
        parser.add_argument('-d', '--debian-codename',
            choices=DEBIAN_VERSIONS.keys(), default='buster',
            help='Which debian version to create. Default: %(default)s')
        parser.add_argument('--use-py2', action='store_true',
            help='Use py2 instead of py3 for saltstack.')

        parser.set_defaults(action=self.cli_create_minion)
        return parser


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


    def cli_create_minion(self, args):
        kwargs = vars(args)
        provider = kwargs.pop('provider')
        minion_id = kwargs.pop('minion_id')
        region = kwargs.pop('region')
        size = kwargs.pop('size')
        private_networking = kwargs.pop('private_networking')
        debian_codename = kwargs.pop('debian_codename')
        use_py2 = kwargs.pop('use_py2')
        try:
            create_minion(
                minion_id,
                provider,
                region,
                size,
                private_networking=private_networking,
                debian_codename=debian_codename,
                use_py2=use_py2,
                **kwargs
            )
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
        sizes = provider.get_sizes()
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


def get_clean_kwargs_from_args(args):
    kwargs = vars(args)
    del kwargs['provider']
    return kwargs


def get_provider(provider_alias, config_path, region):
    return build_provider_from_file(provider_alias, config_path, region=region)


if __name__ == '__main__':
    main()
