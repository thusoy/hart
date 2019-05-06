# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/).


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
