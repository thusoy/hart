set -euo nounset -o noclobber

# Help seed the random pool to make sure any parallel process that might
# generate keys or do TLS has random data to pull from.
echo '{{ random_seed }}' > /dev/random

# Deploy the ssh-canary as one of the first thing to ensure we can connect and
# verify quickly
echo '{{ ssh_canary }}' > /tmp/ssh-canary

# Start conntrack to ensure connections started during init are let through the
# firewall when it is activated later
iptables -A INPUT -m conntrack --ctstate ESTABLISHED -j ACCEPT

# Stop apt from fetching translation files to speed up apt operations
printf '// Added by hart cloud-init\nAcquire::Languages "none";\n' \
    > /etc/apt/apt.conf.d/99hart-translations

# Make sure apt doesn't prompt for anything
apt_get_noninteractive () {
    export DEBIAN_FRONTEND=noninteractive
    apt-get \
        --assume-yes \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        $@
}

{% if wait_for_apt %}
# On some providers (notably, Vultr) there will be a apt-daily systemd service
# that will start when the node boots, causing concurrent access problems for
# this script. Thus wait until other instances are done before continuing, but
# only do so where the jobs to wait on exists, thus the if check.
echo 'Waiting for apt startup tasks to finish'
systemd-run \
    --property="After=apt-daily.service apt-daily-upgrade.service" \
    --wait /bin/true
{% endif %}

# Update the repo to get updated keys and archives, then install https transport
# for apt before adding the salt repo using https, and gnupg for apt-key
apt-get update
apt_get_noninteractive install apt-transport-https gnupg

# Add the salt debian repo key, silencing an inappropriate warning from apt-key
APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 apt-key add - <<EOF
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

# Add the salt debian repo
echo 'deb {{ saltstack_repo }}' > /etc/apt/sources.list.d/saltstack.list

apply_security_updates () {
    local security_list=/tmp/apt-security.list
    grep -ir --no-filename security /etc/apt/sources.list /etc/apt/sources.list.d \
        > "$security_list"
    apt_get_noninteractive upgrade \
        -o Dir::Etc::SourceList="$security_list" \
        -o Dir::Etc::SourceParts="-"
    rm "$security_list"
}

# Update the repo and apply all security updates. If people want to upgrade
# other packages they can do so from salt.
apt-get update
apply_security_updates
