from unittest.mock import MagicMock, Mock

import pytest

from hart.exceptions import UserError
from hart.providers import gce


def test_get_selected_or_default_subnet_none():
    with pytest.raises(UserError):
        gce.get_selected_or_default_subnet([], 'irrelevant')


def test_get_only_alternative():
    first = Mock()
    first.name = 'first'
    ret = gce.get_selected_or_default_subnet([first], None)
    assert ret.name == 'first'


def test_get_several_alternatives():
    first = Mock()
    first.name = 'first'
    second = Mock()
    second.name = 'second'
    with pytest.raises(UserError):
        gce.get_selected_or_default_subnet([first, second], None)


def test_get_selected_or_default_subnet_multiple():
    first = Mock()
    first.name = 'first'
    second = Mock()
    second.name = 'second'
    ret = gce.get_selected_or_default_subnet([first, second], 'first')
    assert ret.name == 'first'


def test_get_selected_or_default_subnet_none_matching():
    first = Mock()
    first.name = 'first'
    second = Mock()
    second.name = 'second'
    with pytest.raises(UserError):
        gce.get_selected_or_default_subnet([first, second], 'third')


def build_gce_provider():
    provider = gce.GCEProvider.__new__(gce.GCEProvider)
    # MagicMock to let the driver's image and disk types be subscripted
    provider.driver = MagicMock()
    provider.region = 'us-east4'
    subnet = Mock()
    subnet.name = 'us-east4'
    provider.driver.ex_list_subnetworks.return_value = [subnet]
    return provider


def create_node(provider, **kwargs):
    kwargs.setdefault('zone', 'us-east4-a')
    kwargs.setdefault('volume_size', 10)
    kwargs.setdefault('volume_type', 'pd-ssd')
    auth_key = Mock()
    provider.create_node('01.db.example.com', 'us-east4', 'bookworm', auth_key,
        'cloud-init', False, ['db'], **kwargs)
    return provider.driver.create_node.call_args[1]


def test_gets_ephemeral_public_ip_by_default():
    provider = build_gce_provider()

    # external_ip is what libcloud (and GCE) calls the public IP
    assert create_node(provider)['external_ip'] == 'ephemeral'


def test_can_be_created_without_public_ip():
    provider = build_gce_provider()

    assert create_node(provider, no_public_ip=True)['external_ip'] is None


def test_instance_name_generation():
    minion_id = '01.db.example.com'
    assert gce.name_from_minion_id(minion_id) == 'hart-com-example-db-01-b64faa'
