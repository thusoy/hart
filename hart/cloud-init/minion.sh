#!/bin/sh

set -euo nounset -o noclobber

# cloud-init script to initialize a salt minion. Only works on debian for now.

minion_config=$(cat <<EOF
{{ minion_config }}
EOF
)

master_pubkey=$(cat <<EOF
{{ master_pubkey }}
EOF
)

### END OF CONFIG ###


# Deploy the ssh-canary as the first thing to ensure we can connect and verify quickly
echo '{{ ssh_canary }}' > /tmp/ssh-canary

# Start conntrack to ensure connections started during init are let through the
# firewall when it is activated later
modprobe nf_conntrack_ipv4 nf_conntrack_ipv6

# Add the salt debian repo key
apt-key add - <<EOF
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v2.0.22 (GNU/Linux)

mQENBFOpvpgBCADkP656H41i8fpplEEB8IeLhugyC2rTEwwSclb8tQNYtUiGdna9
m38kb0OS2DDrEdtdQb2hWCnswxaAkUunb2qq18vd3dBvlnI+C4/xu5ksZZkRj+fW
tArNR18V+2jkwcG26m8AxIrT+m4M6/bgnSfHTBtT5adNfVcTHqiT1JtCbQcXmwVw
WbqS6v/LhcsBE//SHne4uBCK/GHxZHhQ5jz5h+3vWeV4gvxS3Xu6v1IlIpLDwUts
kT1DumfynYnnZmWTGc6SYyIFXTPJLtnoWDb9OBdWgZxXfHEcBsKGha+bXO+m2tHA
gNneN9i5f8oNxo5njrL8jkCckOpNpng18BKXABEBAAG0MlNhbHRTdGFjayBQYWNr
YWdpbmcgVGVhbSA8cGFja2FnaW5nQHNhbHRzdGFjay5jb20+iQE4BBMBAgAiBQJT
qb6YAhsDBgsJCAcDAgYVCAIJCgsEFgIDAQIeAQIXgAAKCRAOCKFJ3le/vhkqB/0Q
WzELZf4d87WApzolLG+zpsJKtt/ueXL1W1KA7JILhXB1uyvVORt8uA9FjmE083o1
yE66wCya7V8hjNn2lkLXboOUd1UTErlRg1GYbIt++VPscTxHxwpjDGxDB1/fiX2o
nK5SEpuj4IeIPJVE/uLNAwZyfX8DArLVJ5h8lknwiHlQLGlnOu9ulEAejwAKt9CU
4oYTszYM4xrbtjB/fR+mPnYh2fBoQO4d/NQiejIEyd9IEEMd/03AJQBuMux62tjA
/NwvQ9eqNgLw9NisFNHRWtP4jhAOsshv1WW+zPzu3ozoO+lLHixUIz7fqRk38q8Q
9oNR31KvrkSNrFbA3D89uQENBFOpvpgBCADJ79iH10AfAfpTBEQwa6vzUI3Eltqb
9aZ0xbZV8V/8pnuU7rqM7Z+nJgldibFk4gFG2bHCG1C5aEH/FmcOMvTKDhJSFQUx
uhgxttMArXm2c22OSy1hpsnVG68G32Nag/QFEJ++3hNnbyGZpHnPiYgej3FrerQJ
zv456wIsxRDMvJ1NZQB3twoCqwapC6FJE2hukSdWB5yCYpWlZJXBKzlYz/gwD/Fr
GL578WrLhKw3UvnJmlpqQaDKwmV2s7MsoZogC6wkHE92kGPG2GmoRD3ALjmCvN1E
PsIsQGnwpcXsRpYVCoW7e2nW4wUf7IkFZ94yOCmUq6WreWI4NggRcFC5ABEBAAGJ
AR8EGAECAAkFAlOpvpgCGwwACgkQDgihSd5Xv74/NggA08kEdBkiWWwJZUZEy7cK
WWcgjnRuOHd4rPeT+vQbOWGu6x4bxuVf9aTiYkf7ZjVF2lPn97EXOEGFWPZeZbH4
vdRFH9jMtP+rrLt6+3c9j0M8SIJYwBL1+CNpEC/BuHj/Ra/cmnG5ZNhYebm76h5f
T9iPW9fFww36FzFka4VPlvA4oB7ebBtquFg3sdQNU/MmTVV4jPFWXxh4oRDDR+8N
1bcPnbB11b5ary99F/mqr7RgQ+YFF0uKRE3SKa7a+6cIuHEZ7Za+zhPaQlzAOZlx
fuBmScum8uQTrEF5+Um5zkwC7EXTdH1co/+/V/fpOtxIg4XO4kcugZefVm5ERfVS
MA===dtMN
-----END PGP PUBLIC KEY BLOCK-----
EOF

# Make sure apt doesn't prompt for anything
apt_get_noninteractive () {
    export DEBIAN_FRONTEND=noninteractive
    apt-get \
        --assume-yes \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        $@
}

# Update the repo to get updated keys and archives, then install https transport for apt
# before adding the salt repo using https
apt-get update
apt_get_noninteractive install apt-transport-https

# Add the salt debian repo
echo 'deb https://repo.saltstack.com/apt/debian/{{ debian_version }}/amd64/{{ salt_branch }} {{ debian_codename }} main' > /etc/apt/sources.list.d/saltstack.list

# Update the packages and upgrade whatever we have locally
apt-get update
apt_get_noninteractive upgrade

# Add a trust root for the salt master to prevent MitM on bootstrap
mkdir -p /etc/salt/pki/minion
echo "$master_pubkey" > /etc/salt/pki/minion/minion_master.pub
echo "$minion_config" > /etc/salt/minion

# Manually create the minion key so that it's available immediately when this script
# terminates, without first trying to contact the salt master
old_umask=$(umask)
umask 266
openssl genrsa -out /etc/salt/pki/minion/minion.pem 2048
umask "$old_umask"
openssl rsa -in /etc/salt/pki/minion/minion.pem -pubout -out /etc/salt/pki/minion/minion.pub

# Install the core packages needed
apt_get_noninteractive install salt-minion

echo 'Hart init script complete'
