from unittest import mock

from hart.providers.ec2 import EC2Provider


def test_get_zones():
    provider = EC2Provider.__new__(EC2Provider)
    provider._ec2 = mock.Mock()
    provider._ec2.describe_availability_zones.return_value = {
        'AvailabilityZones': [
            {'ZoneName': 'us-east-1a', 'State': 'available'},
            {'ZoneName': 'us-east-1b', 'State': 'available'},
            {'ZoneName': 'us-east-1c', 'State': 'impaired'},
        ],
    }

    assert provider.get_zones('us-east-1') == ['us-east-1a', 'us-east-1b']
