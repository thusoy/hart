set -euo nounset -o noclobber

# Help seed the random pool to make sure any parallel process that might
# generate keys or do TLS has random data to pull from.
echo '{{ random_seed }}' > /dev/random

# Deploy the ssh-canary as one of the first thing to ensure we can connect and
# verify quickly
echo '{{ ssh_canary }}' > /tmp/ssh-canary

{% if permit_root_ssh %}
# Some providers (hey google) default to 'PermitRootLogin no' in the ssh config,
# preventing us from being able to connect. Fix this.
grep -qE '^PermitRootLogin no' /etc/ssh/sshd_config && (
    sed -i 's/^PermitRootLogin no/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
    service ssh reload
) || :
{% endif %}

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

cat <<EOF | gpg --dearmor > /usr/share/keyrings/salt-archive-keyring-2023.gpg
-----BEGIN PGP PUBLIC KEY BLOCK-----

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
=ZKPF
-----END PGP PUBLIC KEY BLOCK-----
EOF

# Add the salt debian repo
echo 'deb [signed-by=/usr/share/keyrings/salt-archive-keyring-2023.gpg] {{ saltstack_repo }}' > /etc/apt/sources.list.d/saltstack.list

apply_security_updates () {
    local apt_security_parts
    apt_security_parts=$(mktemp -d)

    # Extract sourcelists in oneline format that contain "security"
    grep --ignore-case \
        --recursive \
        --no-filename \
        --include="*.list" \
        security \
        /etc/apt/sources.list /etc/apt/sources.list.d || true \
        > "$apt_security_parts/security.list"

    # Find deb822-style sourcelists and split the entries into parts by empty
    # lines (which separate entries)
    find /etc/apt/sources.list.d -type f -name '*.sources' -print | while read file; do
        csplit \
            --elide-empty-files \
            --prefix "$apt_security_parts/$(basename $file)" \
            --quiet \
            --suppress-match \
            --suffix-format "%02d.sources" \
            "$file" \
            '/^$/' '{*}'
    done

    # Delete deb822-style files that are not security related
    grep --files-without-match \
        --recursive \
        --null \
        security "$apt_security_parts" \
        | xargs --null --no-run-if-empty rm

    apt_get_noninteractive upgrade \
        -o Dir::Etc::SourceList="-" \
        -o Dir::Etc::SourceParts="$apt_security_parts"
    rm -rf "$apt_security_parts"
}

# Update the repo and apply all security updates. If people want to upgrade
# other packages they can do so from salt.
apt-get update
apply_security_updates
