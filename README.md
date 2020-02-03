Hart
====

A highly opinionated, secure alternative to salt-cloud.


Local testing
=============

Due to the nature of the project (requiring a salt master and lots of
interaction with third-party APIs) it's hard to write good unit tests. There is
a limited set that can be run as follows:

    $ ./test

There's also a small set of integration tests that require setting up test
accounts with the different providers (put credentials in `hart.toml`):

    $ ./test -m integration

If you're working on a single provider and don't want to test all of them, use
standard pytest filtering:

    $ ./test -m integration -k digitalocean


## Manual testing

You need a salt master to run the code from. There's a helper script in
`./tools/run-in-docker.sh` that starts a shell in a docker container with
salt-master and hart installed (and the saltmaster ports forwarded to the
container). Start the salt-master with `salt-master -d`. Unless you have a
publicly routeable IP, you probably want to set up a ssh port forward with
`ssh $HOST -N -R 0.0.0.0:4505:127.0.0.1:4505 -R 0.0.0.0:4506:127.0.0.1:4506`
to a host that has a routeable IP for the new minions to be able to connect to
the container (also make sure ports 4505 and 4506 is allowed through the
firewall to that server: `sudo iptables -I INPUT -p tcp -m multiport --dports
4505,4506 -j ACCEPT`). Set the public IP as the master for the minions by
setting `minion_config: {'master': '$IP'}` in the call to `create_minion`.
Create a file `hart.toml` in the root of the repo with credentials to use for
development.


License
=======

This project uses the [Hippocratic License](https://firstdonoharm.dev/), and is
thus freely available to use for purposes that do not infringe on the United
Nations Universal Declaration of Human Rights.
