from unittest.mock import Mock

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


def test_instance_name_generation():
    minion_id = '01.db.example.com'
    assert gce.name_from_minion_id(minion_id) == 'hart-com-example-db-01-b64faa'
