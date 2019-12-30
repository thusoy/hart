Hart
====

A highly opinionated, secure alternative to salt-cloud.


Local testing
=============

You need a salt master to run the code from. There's a helper script in `./tools/run-in-docker.sh` that starts a shell in a docker container with salt-master and hart installed (and the saltmaster ports forwarded to the container). Start the salt-master with `salt-master -d`. Unless you have a publicly routeable IP, you probably want to set up a ssh port forward with `ssh $HOST -N -R 0.0.0.0:4505:127.0.0.1:4505 -R 0.0.0.0:4506:127.0.0.1:4506` to a host that has a routeable IP for the new minions to be able to connect to the container. Set the public IP as the master for the minions by setting `minion_config: {'salt': '$IP'}` in the call to `create_minion`. Create a file `hart.toml` in the root of the repo with credentials to use for development.
