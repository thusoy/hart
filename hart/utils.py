import base64
import datetime
import os
from collections import namedtuple

import jinja2

from .constants import DEBIAN_VERSIONS
from .exceptions import UserError


HartNode = namedtuple('HartNode', 'minion_id public_ip node provider ssh_key ssh_canary node_extra')


def create_token():
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')


def get_cloud_init_template(template_name='minion.sh'):
    template_directory = os.path.join(os.path.dirname(__file__), 'cloud-init')
    environment = jinja2.Environment(loader=jinja2.FileSystemLoader(template_directory))
    return environment.get_template(template_name)


def get_saltstack_repo_url(debian_codename, salt_branch, use_py2):
    debian_version = DEBIAN_VERSIONS[debian_codename]
    if use_py2 and debian_version > 9:
        raise UserError('saltstack py2 is only available for debian stretch and older')
    if not use_py2 and debian_version < 9:
        raise UserError('saltstack py3 is only available for debian stretch and newer')
    return 'https://repo.saltstack.com/%s/debian/%s/amd64/%s %s main' % (
        'apt' if use_py2 else 'py3', debian_version, salt_branch, debian_codename)


def build_ssh_key_name(minion_id):
    current_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
    return 'hart-temp-for-%s-at-%s' % (minion_id, current_date)
