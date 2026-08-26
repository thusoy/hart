'''
A local store of the minions created by hart.

The store enables looking up which provider a minion was created with, where
it's located and which IPs it has, without querying the providers. It's a
single JSON document to make it easy to consume from other tools (like a
custom salt module) without importing hart. The document looks like this:

{
    "version": 1,
    "minions": {
        "<minion_id>": {
            "minion_id": "<minion_id>",
            "provider": "ec2",
            "region": "us-east-1",
            "zone": "us-east-1a",
            "size": "t3.micro",
            "debian_codename": "bookworm",
            "roles": ["consumer"],
            "public_ips": ["203.0.113.5"],
            "private_ips": ["10.0.0.5"],
            "node_id": "i-0123456789abcdef0",
            "node_name": "minion.us-east-1.ec2.consumer",
            "created_at": "2026-08-06T12:00:00+00:00"
        }
    }
}

"node_id" and "node_name" is the identity of the node at the provider, which
might differ from the minion id (like on GCE, where the instance name has to
be a valid DNS label).

Writers hold a lock on a sidecar <store>.lock file and replace the store
atomically, thus readers can read the JSON directly without any locking.
'''

import datetime
import fcntl
import grp
import json
import os
import tempfile

DEFAULT_STORE_PATH = '/var/lib/hart/minions.json'
STORE_VERSION = 1


def get_store_path(path=None):
    return path or os.environ.get('HART_MINION_STORE') or DEFAULT_STORE_PATH


def build_record(
        minion_id,
        provider_alias,
        node,
        region=None,
        zone=None,
        size=None,
        debian_codename=None,
        roles=None,
        created_at=None,
        ):
    if created_at is None:
        created_at = datetime.datetime.now(datetime.timezone.utc)
    if isinstance(created_at, datetime.datetime):
        created_at = created_at.isoformat(timespec='seconds')
    return {
        'minion_id': minion_id,
        'provider': provider_alias,
        'region': region,
        'zone': zone,
        'size': size,
        'debian_codename': debian_codename,
        'roles': list(roles) if roles else [],
        'public_ips': list(node.public_ips or []),
        'private_ips': list(node.private_ips or []),
        'node_id': node.id,
        'node_name': node.name,
        'created_at': created_at,
    }


def add_minion(record, path=None):
    def update(minions):
        minions[record['minion_id']] = record
        return True, None
    return _update_store(update, path)


def remove_minion(minion_id, path=None):
    '''Returns the removed record, or None if the minion wasn't in the store.'''
    def update(minions):
        record = minions.pop(minion_id, None)
        return record is not None, record
    return _update_store(update, path)


def get_minion(minion_id, path=None):
    return load_store(path)['minions'].get(minion_id)


def list_minions(path=None):
    return sorted(load_store(path)['minions'].values(), key=lambda r: r['minion_id'])


def load_store(path=None):
    path = get_store_path(path)
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {'version': STORE_VERSION, 'minions': {}}


def _update_store(update, path=None):
    path = get_store_path(path)
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    with open(path + '.lock', 'w') as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            store = load_store(path)
            changed, retval = update(store['minions'])
            if changed:
                store['version'] = STORE_VERSION
                _replace_store(store, path)
            return retval
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _replace_store(store, path):
    directory = os.path.dirname(path) or '.'
    # Write to a tempfile in the same directory to be able to atomically
    # rename it over the old store
    with tempfile.NamedTemporaryFile(
            mode='w',
            dir=directory,
            prefix='.%s-' % os.path.basename(path),
            delete=False) as fh:
        try:
            json.dump(store, fh, indent=2, sort_keys=True)
            fh.write('\n')
            _set_store_permissions(fh.name)
        except:
            os.remove(fh.name)
            raise
    os.rename(fh.name, path)


def _set_store_permissions(path):
    # We don't consider the contents of the store super sensitive, but make a
    # best-effort attempt at limiting it to root and the salt group (so that
    # custom salt modules can read it directly) to avoid disclosing the entire
    # fleet to anyone on the host.
    try:
        salt_gid = grp.getgrnam('salt').gr_gid
    except KeyError:
        return
    try:
        os.chown(path, -1, salt_gid)
        os.chmod(path, 0o640)
    except PermissionError:
        pass
