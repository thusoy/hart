#!/bin/sh

# cloud-init script to initialize a salt minion. Only works on Debian.

{% include 'base.sh' %}

# Add a trust root for the salt master to prevent MitM on bootstrap
mkdir -p /etc/salt/pki/minion
cat > /etc/salt/pki/minion/minion_master.pub <<EOF
{{ master_pubkey }}
EOF
cat > /etc/salt/minion <<EOF
################################
# Salt minion config from hart #
################################

{{ minion_config }}
EOF

# Manually create the minion key so that it's available immediately when this script
# terminates, without first trying to contact the salt master
old_umask=$(umask)
umask 266
openssl genrsa -out /etc/salt/pki/minion/minion.pem 2048
umask "$old_umask"
openssl rsa -in /etc/salt/pki/minion/minion.pem -pubout -out /etc/salt/pki/minion/minion.pub

# Install the core packages needed
apt_get_noninteractive install salt-minion

# Salt versions 3006.{8,9} and 3007.{0,1} has a bug where there's a warning
# always logged from this module, just remove it to prevent this.
# Ref. https://github.com/saltstack/salt/issues/66467
rm -f \
    /opt/saltstack/salt/lib/python3.10/site-packages/salt/utils/psutil_compat.py \
    /opt/saltstack/salt/lib/python3.10/site-packages/salt/utils/__pycache__/psutil_compat.cpython-310.pyc

echo 'hart-init-complete'
