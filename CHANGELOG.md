# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/).


0.14.8 - 2021-08-15
-------------------

## Fixed
- Connection to nodes that include `PermitRootLogin no` in the default sshd config (notably GCE).


0.14.7 - 2021-06-23
-------------------

## Fixed
- Handle more possible error cases for retry in initial connectivity check.


0.14.6 - 2021-06-22
-------------------

## Fixed
- Bug in `hart.utils.remove_argument_from_parser` if argument had multiple option strings.


0.14.5 - 2021-06-22
-------------------

## Changed
- The CLI ArgumentParser now defines `conflict_handler=resolve` to let subclasses override
  defaults without having to first remove the existing argument.

## Added
- `hart.utils.remove_argument_from_parser` to help CLI subclasses remove arguments that
  are not relevant for them.

## Fixed
- Retry initial pings and increase timeouts to reduce error rate when creating minions.


0.14.4 - 2021-04-26
-------------------

## Fixed
- Enable passing defaults on the CLI to override role config.
- Fix crash if using provider default size.


0.14.3 - 2021-04-26
-------------------

## Fixed
- Fix parser crash introduced in 0.14.2.


0.14.2 - 2021-04-26
-------------------

## Fixed
- Allow all create-minion arguments when creating role.


0.14.1 - 2021-04-26
-------------------

## Fixed
- Merge cli parameters with parameters from role parameters in the config file.


0.14.0 - 2021-04-26
-------------------

## Added
- Support for the af-south-1 and eu-south-1 EC2 regions.
- You can now manage a high-level resource called a "role". A role is basically
  a named group of parameters to create a minion, and is usually what you'd use
  in the salt topfile to allocate states to a minion.

## Changed
- Digital Ocean is no longer used as the default provider if none is specified.


0.13.1 - 2021-02-17
-------------------

## Fixed
- DO crash around `--enable-ipv6` usage.


0.13.0 - 2021-02-17
-------------------

## Changed
- GCE now defaults to turning off OSLogin, assuming you want to use salt to manage ssh keys. This
  can be disabled with the flag `--enable-oslogin`.

## Added
- You can enable IPv6 on DO droplets by passing `--enable-ipv6`.

## Fixed
- GCE picks the only available subnet if none was specified.
- GCE hang when creating salt-master.
- EC2 crashed if trying to list available subnets.
- EC2 can now manage minions in non-standard VPCs.


0.12.3 - 2020-04-29
-------------------

## Fixed
- Crash when printing user errors.
- Minion keys are no longer on disk if node failed to connect.
- GCE will now automatically pick the available subnet and network in a zone, and enables
  specifying this with --subnet if ambigious.


0.12.2 - 2020-04-07
-------------------

## Fixed
- GCE didn't detect init script completion after some changes on Google's side.


0.12.1 - 2020-03-16
-------------------

## Fixed
- Crash when creating minion when fetching pubkey.


0.12.0 - 2020-03-14
-------------------

## Added
- `-v|--version` to print the version on the CLI.
- Ability to bootstrap a saltmaster with the command `create-master`.


0.11.0 - 2020-02-16
-------------------

## Added
- You can now specify the target salt branch from the CLI.
- You can now add extra minion config on the CLI.

## Changed
- GCE VM names are now prefixed with `hart-`. If you created any GCE VMs on 0.10.x you'll have to
  manually add this prefix in the console to be able to destroy the minions. This was done to not
  crash if trying to create a minion with a leading digit in the id.
- Only security updates are now applied when the minion is created, whereas earlier we upgraded all
  packages. If you want to upgrade all packages you should do so from salt instead.

## Fixed
- The minion's random pool is now seeded from the saltmaster early in the startup process to make
  early key generation stronger.


0.10.2 - 2020-02-04
-------------------

## Fixed
- GCE crash when trying to delete a node.


0.10.1 - 2020-02-03
-------------------

## Fixed
- Fix GCE minion id hash crash.


0.10.0 - 2020-02-03
-------------------

## Changed
- The license has been changed from MIT to the Hippocratic License to deny use that infringes on the
  UN's declaration of human rights.
- The entire contents of the cloud-init/startup log is now printed when a node is created, instead
  of just the last 10 lines from when we connect.
- EC2 `list-sizes` without a region will now log a warning instead of erroring.

## Added
- `-R` as a shorthand for `--region`.
- GCE provider.


0.9.0 - 2019-12-30
------------------

## Added
- Support for Debian Buster. This is now the default distribution if none is specified.

## Changed
- Saltstack will now default to use Python 3 as Python 2 is approaching EOL. You can continue using
  Python 2 by passing `--use-py2` to `create-minion`.
- Some timeouts have been increased to minimize the amount of timeouts when nothing has failed.

## Fixed
- Couldn't list sizes with vultr provider.
- EC2 failed if not specifying --volume-size or --volume-type.


0.8.0 - 2019-08-14
------------------

## Fixed
- The EC2 provider will set instance tags if given in key=val format.
- The Vultr provider doesn't wrap the tag in brackets anymore.
- Vultr now automatically adds private IPs to the node if -p is given.

## Added
- Extensible CLI for to create and destroy minions, and listing regions and sizes.
- Ability to customize EC2 root volume size.


0.7.2 - 2019-08-09
------------------

## Fixed
- Crash when destroying node by id.


0.7.1 - 2019-08-09
------------------

## Fixed
- EC2 couldn't destroy a node.


0.7.0 - 2019-08-09
------------------

## Fixed
- Make ap-east-1 and me-south-1 work for EC2.

## Changed
- Fully replaced libcloud with boto3 for EC2.


0.6.1 - 2019-06-03
------------------

## Fixed
- EC2 size listing now filters out options that wouldn't be launched by hart, and also ensures all options are shown.
- Crash when listing EC2 sizes in São Paulo.


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
