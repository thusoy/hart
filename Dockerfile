FROM debian:trixie-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-virtualenv \
        curl \
        gnupg2 && \
    curl -fsSL https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public \
        | gpg --dearmor > /etc/apt/keyrings/salt-archive-keyring-2023.pgp && \
    echo "deb [signed-by=/etc/apt/keyrings/salt-archive-keyring-2023.pgp arch=amd64] https://packages.broadcom.com/artifactory/saltproject-deb/ stable main" > /etc/apt/sources.list.d/salt.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends salt-master

# Set a utf-8 locale to make hart properly decode utf-8 from hosts (I think
# this should have been set explicitly by paramiko)
ENV LC_CTYPE=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# Copying in dependencies to not have to reinstall for every change in the source code
RUN python3 -m virtualenv -p $(which python3) /app/venv && \
    /app/venv/bin/pip install -U pip setuptools && \
    /app/venv/bin/pip install \
        apache-libcloud \
        jinja2 \
        paramiko \
        pyyaml \
        toml \
        ifaddr \
        boto3

COPY setup.py /app/

# Need to copy in enough files to install, but leaving out most to not have to rebuild on every change
COPY hart/version.py hart/__main__.py /app/hart/

RUN /app/venv/bin/pip install -e .
