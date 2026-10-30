import argparse
from unittest.mock import MagicMock, Mock, patch

from libcloud.common import google
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


def test_authenticates_with_service_account_key():
    with patch.object(gce, 'get_driver') as get_driver:
        gce.GCEProvider(user_id='hart@example.iam.gserviceaccount.com',
            key='private-key', project='example')

    get_driver.return_value.assert_called_once_with(
        user_id='hart@example.iam.gserviceaccount.com', key='private-key',
        project='example', auth_type='SA')


def test_authenticates_with_vm_identity_without_key():
    with patch.object(gce, 'get_driver') as get_driver:
        gce.GCEProvider(project='example')

    kwargs = get_driver.return_value.call_args[1]
    assert kwargs['auth_type'] == 'GCE'
    assert kwargs['project'] == 'example'


def test_vm_identity_gets_token_from_metadata_server(tmp_path, monkeypatch):
    # Builds a real libcloud driver, to catch arguments libcloud rejects
    monkeypatch.setenv('HOME', str(tmp_path))
    paths = []
    def get_metadata(path='', retry_failed=None):
        paths.append(path)
        return 200, '', '{"access_token": "token", "expires_in": 3599}'
    monkeypatch.setattr(google, '_get_gce_metadata', get_metadata)

    provider = gce.GCEProvider(project='example')

    assert provider.driver.connection.oauth2_credential.access_token == 'token'
    assert paths == ['/instance/service-accounts/default/token']


@pytest.mark.parametrize('credentials', [
    {'user_id': 'hart@example.iam.gserviceaccount.com'},
    {'key': 'private-key'},
])
def test_rejects_partial_service_account_credentials(credentials):
    with patch.object(gce, 'get_driver'):
        with pytest.raises(UserError):
            gce.GCEProvider(project='example', **credentials)


def build_gce_provider(guest_os_features=('SEV_CAPABLE', 'SEV_SNP_CAPABLE')):
    provider = gce.GCEProvider.__new__(gce.GCEProvider)
    # MagicMock to let the driver's image and disk types be subscripted
    provider.driver = MagicMock()
    provider.region = 'us-east4'
    subnet = Mock()
    subnet.name = 'us-east4'
    provider.driver.ex_list_subnetworks.return_value = [subnet]
    image = Mock()
    image.extra = {
        'selfLink': 'projects/debian-cloud/global/images/debian-13-trixie-v1',
        'guestOsFeatures': [{'type': feature} for feature in guest_os_features],
    }
    provider.driver.ex_get_image.return_value = image
    provider.driver._create_node_req.return_value = (
        '/zones/us-east4-a/instances', {'name': '01-db-example-com'})
    return provider


def create_node(provider, **kwargs):
    kwargs.setdefault('zone', 'us-east4-a')
    kwargs.setdefault('volume_size', 10)
    kwargs.setdefault('volume_type', 'pd-ssd')
    auth_key = Mock()
    provider.create_node('01.db.example.com', 'us-east4', 'trixie', auth_key,
        'cloud-init', False, ['db'], **kwargs)
    return provider.driver._create_node_req.call_args[1]


def posted_instance(provider):
    return provider.driver.connection.async_request.call_args[1]['data']


def test_posts_the_built_instance_and_returns_the_node():
    provider = build_gce_provider()

    create_node(provider)

    provider.driver.connection.async_request.assert_called_once_with(
        '/zones/us-east4-a/instances', method='POST',
        data=posted_instance(provider))
    provider.driver.ex_get_node.assert_called_once_with(
        gce.name_from_minion_id('01.db.example.com'),
        provider.driver.ex_get_zone.return_value.name)


def test_is_neither_shielded_nor_confidential_by_default():
    provider = build_gce_provider()

    kwargs = create_node(provider)
    instance = posted_instance(provider)

    assert 'shieldedInstanceConfig' not in instance
    assert 'confidentialInstanceConfig' not in instance
    assert 'minCpuPlatform' not in instance
    assert kwargs['ex_on_host_maintenance'] is None
    assert 'interface' not in kwargs['ex_disks_gce_struct'][0]


def test_shielded_enables_all_shielded_vm_options():
    provider = build_gce_provider()

    create_node(provider, shielded=True)

    assert posted_instance(provider)['shieldedInstanceConfig'] == {
        'enableSecureBoot': True,
        'enableVtpm': True,
        'enableIntegrityMonitoring': True,
    }


def test_confidential_sev_live_migrates_on_n2d():
    provider = build_gce_provider()

    kwargs = create_node(provider, size='n2d-standard-4', confidential_type='SEV')

    instance = posted_instance(provider)
    assert instance['confidentialInstanceConfig'] == {'confidentialInstanceType': 'SEV'}
    assert 'minCpuPlatform' not in instance
    assert kwargs['ex_on_host_maintenance'] == 'MIGRATE'
    # Confidential VMs only support NVMe disks
    assert kwargs['ex_disks_gce_struct'][0]['interface'] == 'NVME'


def test_confidential_sev_terminates_on_maintenance_on_c4d():
    provider = build_gce_provider()

    kwargs = create_node(provider, size='c4d-standard-4', confidential_type='SEV')

    assert kwargs['ex_on_host_maintenance'] == 'TERMINATE'


def test_confidential_sev_snp_needs_milan_and_terminates_on_maintenance():
    provider = build_gce_provider()

    kwargs = create_node(provider, size='n2d-standard-4',
        confidential_type='SEV_SNP')

    instance = posted_instance(provider)
    assert instance['confidentialInstanceConfig'] == {
        'confidentialInstanceType': 'SEV_SNP'}
    assert instance['minCpuPlatform'] == 'AMD Milan'
    assert kwargs['ex_on_host_maintenance'] == 'TERMINATE'


def test_confidential_sev_snp_leaves_cpu_platform_to_single_platform_families():
    provider = build_gce_provider()

    create_node(provider, size='c4d-standard-4', confidential_type='SEV_SNP')

    assert 'minCpuPlatform' not in posted_instance(provider)


def test_rejects_confidential_type_the_image_does_not_support():
    provider = build_gce_provider(guest_os_features=('SEV_CAPABLE',))

    with pytest.raises(UserError):
        create_node(provider, size='n2d-standard-4', confidential_type='SEV_SNP')

    provider.driver.connection.async_request.assert_not_called()


def test_explicit_min_cpu_platform():
    provider = build_gce_provider()

    create_node(provider, min_cpu_platform='AMD Turin')

    assert posted_instance(provider)['minCpuPlatform'] == 'AMD Turin'


def test_parses_shielded_and_confidential_arguments():
    provider = build_gce_provider()
    parser = argparse.ArgumentParser()
    provider.add_create_minion_arguments(parser)

    args = parser.parse_args(['--shielded', '--confidential-type', 'SEV_SNP',
        '--min-cpu-platform', 'AMD Milan'])

    assert args.shielded is True
    assert args.confidential_type == 'SEV_SNP'
    assert args.min_cpu_platform == 'AMD Milan'


def test_only_offers_confidential_types_debian_supports():
    provider = build_gce_provider()
    parser = argparse.ArgumentParser()
    provider.add_create_minion_arguments(parser)

    with pytest.raises(SystemExit):
        parser.parse_args(['--confidential-type', 'TDX'])


def test_gets_ephemeral_public_ip_by_default():
    provider = build_gce_provider()

    # external_ip is what libcloud (and GCE) calls the public IP
    assert create_node(provider)['external_ip'] == 'ephemeral'


def test_can_be_created_without_public_ip():
    provider = build_gce_provider()

    assert create_node(provider, no_public_ip=True)['external_ip'] is None


def test_uses_default_service_account_with_ops_scopes_by_default():
    provider = build_gce_provider()

    assert create_node(provider)['ex_service_accounts'] == [{
        'scopes': [
            'https://www.googleapis.com/auth/logging.write',
            'https://www.googleapis.com/auth/monitoring.write',
        ],
    }]


def test_can_be_created_with_service_account_and_scopes():
    provider = build_gce_provider()

    service_accounts = create_node(provider,
        service_account='saltmaster@example.iam.gserviceaccount.com',
        scopes=['cloud-platform'])['ex_service_accounts']

    assert service_accounts == [{
        'email': 'saltmaster@example.iam.gserviceaccount.com',
        'scopes': ['cloud-platform'],
    }]


def test_parses_service_account_and_scopes_arguments():
    provider = build_gce_provider()
    parser = argparse.ArgumentParser()
    provider.add_create_minion_arguments(parser)

    args = parser.parse_args(['--service-account', 'sa@example.com',
        '--scopes', 'cloud-platform,logging.write'])

    assert args.service_account == 'sa@example.com'
    assert args.scopes == ['cloud-platform', 'logging.write']


def test_get_zones():
    provider = build_gce_provider()
    region = Mock()
    region.name = 'us-east4'
    zone_a = Mock()
    zone_a.name = 'us-east4-a'
    zone_b = Mock()
    zone_b.name = 'us-east4-b'
    region.zones = [zone_a, zone_b]
    provider.driver.ex_list_regions.return_value = [region]

    assert provider.get_zones('us-east4') == ['us-east4-a', 'us-east4-b']


def test_get_zones_unknown_region():
    provider = build_gce_provider()
    provider.driver.ex_list_regions.return_value = []

    with pytest.raises(UserError):
        provider.get_zones('us-east4')


def test_instance_name_generation():
    minion_id = '01.db.example.com'
    assert gce.name_from_minion_id(minion_id) == 'hart-com-example-db-01-b64faa'


def test_gets_private_ip_from_subnet_by_default():
    provider = build_gce_provider()

    # internal_ip is what libcloud (and GCE) calls the private IP
    assert create_node(provider)['internal_ip'] is None


def test_can_use_reserved_public_address():
    provider = build_gce_provider()
    address = Mock()
    provider.driver.ex_get_address.return_value = address

    external_ip = create_node(provider, public_address='saltmaster')['external_ip']

    assert external_ip is address
    provider.driver.ex_get_address.assert_called_once_with('saltmaster',
        region='us-east4')


def test_can_use_reserved_private_address():
    provider = build_gce_provider()
    address = Mock()
    provider.driver.ex_get_address.return_value = address

    internal_ip = create_node(provider,
        private_address='saltmaster-internal')['internal_ip']

    assert internal_ip is address
    provider.driver.ex_get_address.assert_called_once_with('saltmaster-internal',
        region='us-east4')


def test_rejects_public_address_together_with_no_public_ip():
    provider = build_gce_provider()

    with pytest.raises(UserError):
        create_node(provider, public_address='saltmaster', no_public_ip=True)


def test_parses_address_arguments():
    provider = build_gce_provider()
    parser = argparse.ArgumentParser()
    provider.add_create_minion_arguments(parser)

    args = parser.parse_args(['--public-address', 'saltmaster',
        '--private-address', 'saltmaster-internal'])

    assert args.public_address == 'saltmaster'
    assert args.private_address == 'saltmaster-internal'


def test_rejects_unknown_reserved_address():
    provider = build_gce_provider()
    provider.driver.ex_get_address.side_effect = google.ResourceNotFoundError(
        'not found', 404, None)

    with pytest.raises(UserError):
        create_node(provider, public_address='missing')
