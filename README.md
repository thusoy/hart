# Hart

A highly opinionated, secure alternative to salt-cloud.


## Provider setup

Hart reads configuration from `/etc/hart.toml` if you don't specify a custom
file with `--config`. This should be a TOML file with the following structure:

```toml
[providers.do]
token = "<digital ocean token>"

[providers.ec2]
aws_access_key_id = "<access key id>"
aws_secret_access_key = "<secret access key>"

[providers.gce]
project = "<project_id from the service account credentials>"
user_id = "<client_email from the service account credentials>"
key = "<private_key from the service account credentials>"

[providers.vultr]
token = "<vultr api token>"
```

Only providers you're planning to use are required.


## Configure roles

The most high-level interface to create minions is
`hart create-minion-from-role <role>`. You define parameters for each role in
the hart config file:


```toml
[providers.do]
token = "<digital ocean token>"
# Define a default naming scheme for minions
role_naming_scheme = "{unique_id}.{region}.{provider}.{role}.example.com"
# Define a default region for this provider
region = "sfo3"

[roles.db]
size = "s-4vcpu-8gb"

[roles.app]
size = "s-2vcpu-2gb"

[roles.app.ec2]
# You can override parameters for a role when running under a given provider
subnet = "<some-ec2-subnet>"
size = "t3.medium"

[roles.app.do.nyc3]
# You can override parameters for each region in each provider too
size = "s-3vcpu-3gb"
```

The available parameters are the same as those used by the lower-level API
`hart create-minion`.


## Local testing

Due to the nature of the project (requiring a salt master and lots of
interaction with third-party APIs) it's hard to write good unit tests. There is
a limited set that can be run as follows:

    $ ./test

There's also a small set of integration tests that require setting up test
accounts with the different providers (put credentials in `hart.toml` in the
root of the repo):

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
including `--minion-config '{"master": "$IP"}'` when calling `create-minion`.
Create a file `hart.toml` in the root of the repo with credentials to use for
development.


## License

This project uses the [Hippocratic License](https://firstdonoharm.dev/), and is
thus freely available to use for purposes that do not violate human rights.
