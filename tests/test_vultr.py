import pytest

from hart.providers import vultr


def test_get_device_from_interfaces():
    device_name, next_label = vultr.get_device_and_next_label_from_interfaces({
        'lo': {
            'inet': [{
                'address': '127.0.0.1',
                'label': 'lo',
            }]
        },
        'ens3': {
            'inet': [{
                'address': '1.2.3.4',
            }, {
                'address': '2.3.4.5',
                'label': 'ens3:0',
            }]
        }
    }, '1.2.3.4')
    assert device_name == 'ens3'
    assert next_label == 'ens3:1'


def test_get_device_from_missing_interface():
    with pytest.raises(ValueError):
        vultr.get_device_and_next_label_from_interfaces({}, '1.2.3.4')
