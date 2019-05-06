#!/bin/sh

set -e

./venv/bin/pylint --rcfile .pylintrc hart
