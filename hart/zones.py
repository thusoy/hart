import random

from . import minion_store
from .exceptions import UserError

# Sentinel zone name that means "pick the zone with the fewest minions of the
# same role", based on the local minion store
DISTRIBUTED_ZONE = 'distributed'


def pick_distributed_zones(provider, region, roles, count=1):
    '''Pick the zones in the region that keep minions evenly distributed.

    Returns `count` zones, each chosen to be the zone with the fewest existing
    minions that share a role with the new minion (counting the other zones
    picked in the same call). Existing minions are counted from the local
    minion store, so backfill it with import-minion before relying on this.
    Ties are broken randomly, so with no prior minions this picks random
    zones.
    '''
    zones = provider.get_zones(region)
    if not zones:
        raise UserError('No zones found in %s to distribute minions across' % region)

    zone_counts = {zone: 0 for zone in zones}
    for record in minion_store.list_minions():
        if record['provider'] != provider.alias or record['region'] != region:
            continue
        if roles and not set(roles) & set(record['roles'] or []):
            continue
        if record.get('zone') in zone_counts:
            zone_counts[record['zone']] += 1

    # Shuffle the candidates so that min() breaks ties randomly
    candidates = list(zone_counts)
    random.shuffle(candidates)

    picked = []
    for _ in range(count):
        zone = min(candidates, key=lambda candidate: zone_counts[candidate])
        zone_counts[zone] += 1
        picked.append(zone)

    return picked
