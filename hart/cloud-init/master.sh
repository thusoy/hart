#!/bin/sh

# cloud-init script to initialize a salt master. Only works on Debian.

{% include 'base.sh' %}

# Create a dedicated user for saltstack since they don't do it by default
# Ref. https://github.com/saltstack/salt/issues/38871
adduser saltmaster --system --shell /usr/sbin/nologin --group --home /etc/salt

cat > /etc/salt/minion <<EOF
##########################################
# Temporary salt minion config from hart #
##########################################

{{ minion_config }}
EOF

# Install the core packages needed
apt_get_noninteractive install salt-master salt-minion

# Install hart
apt_get_noninteractive install python3 python3-venv
python3 -m venv /opt/hart-venv
/opt/hart-venv/bin/pip install -U pip setuptools wheel
/opt/hart-venv/bin/pip install hart
ln -s /opt/hart-venv/bin/hart /usr/bin/hart
