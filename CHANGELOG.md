# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/).

0.6.0 - 2019-06-02
------------------

## Added
- `provider.list_sizes()` to list available instance sizes in the given region.
- `provider.list_regions()` to list available regions. For EC2 this includes the available zones.

## Fixed
- Private networking is now initialized correctly on Vultr.


0.5.0 - 2019-05-11
------------------

## Changed
- EC2 now creates a temporary security group to use for the initial connection. Adding a security
  group for steady-state operation will have to be done manually at a later stage.
- `destroy_node` now only takes in a node as returned by `create_node`.

## Removed
- `create_node` no longer accepts the `security_groups` parameter.


0.4.2 - 2019-05-06
------------------

## Fixed
- Fix crash when creating node with duplicate name.
- Increase initial connect timeout from 45s to 90s.


0.4.1 - 2019-05-06
------------------

## Fixed
- Fix harcoded zone in ec2 provider.


0.4.0 - 2019-05-06
------------------

## Added
- Make it optional to specify EC2 subnet when there's only one.

## Fixed
- Restored a check that prevents overwriting existing minions.


0.3.4 - 2019-05-06
------------------

## Fixed
- Error when cleaning up authorized_keys on ec2.


0.3.3 - 2019-05-06
------------------

Yanked.


0.3.2 - 2019-05-06
------------------

## Fixed
- Permissions error on create-minion on ec2.


0.3.1 - 2019-05-06
------------------

## Fixed
- Constructor bug for DO provider.


0.3.0 - 2019-05-06
------------------

## Changed
- Split `create_minion` -> (`create_node`, `connect_minion`) to enable running steps in between.

## Added
- `destroy_minion`, `destroy_node` and `disconnect_minion`.


0.2.0 - 2019-05-06
------------------

## Added
- `build_provider_from_file` to simplify loading from config file.

## Fixed
- Missing cloud-init files.


0.1.0 - 2019-05-06
------------------

First release!
