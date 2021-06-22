from unittest import mock

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


def test_add_private_ip_to_device():
    with mock.patch('hart.providers.vultr.subprocess') as mock_subprocess:
        vultr.add_ip_to_device('minion', 'private', 'ens7', '10.0.0.1', '255.255.240.0')
    mock_subprocess.run.assert_called_with([
        'salt',
        'minion',
        'file.write',
        '/etc/network/interfaces.d/20-hart-private-ip',
        "args=['auto ens7', 'iface ens7 inet static', 'address 10.0.0.1', 'netmask 255.255.240.0', 'mtu 1450']",
    ], check=True)


def test_add_reserved_ip_to_device():
    with mock.patch('hart.providers.vultr.subprocess') as mock_subprocess:
        vultr.add_ip_to_device('minion', 'reserved', 'ens3:0', '1.2.3.4', '255.255.255.0')
    mock_subprocess.run.assert_called_with([
        'salt',
        'minion',
        'file.write',
        '/etc/network/interfaces.d/20-hart-reserved-ip',
        "args=['auto ens3:0', 'iface ens3:0 inet static', 'address 1.2.3.4', 'netmask 255.255.255.0']",
    ], check=True)


def test_get_device_from_missing_interface():
    with pytest.raises(ValueError):
        vultr.get_device_and_next_label_from_interfaces({}, '1.2.3.4')
