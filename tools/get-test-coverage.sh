#!/bin/sh

./venv/bin/py.test \
    -m 'not integration' \
    --cov hart \
    --cov-config .coveragerc \
    --cov-report html:coverage \
    tests/ \
    "$@"

open coverage/index.html
