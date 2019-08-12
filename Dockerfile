FROM debian:stretch-slim as base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-virtualenv \
        curl \
        gnupg2 && \
    curl -s https://repo.saltstack.com/apt/debian/9/amd64/latest/SALTSTACK-GPG-KEY.pub \
        | APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 apt-key add - && \
    apt-get install -y --no-install-recommends \
        salt-master

# Silence pip warnings about python2 EOL
ENV PYTHONWARNINGS=ignore:DEPRECATION
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
