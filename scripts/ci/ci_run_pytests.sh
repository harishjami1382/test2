#!/usr/bin/env bash
# Script to install all the dependencies and run unit tests using pytest

# Install all the dependencies required
apt-get update -y
apt-get install libsasl2-dev -y
apt-get install unixodbc-dev -y

# Install all the packages including optional packages using pip
pip install -r requirements/requirements-python3.7.txt
pip install -r tests/test_requirements.txt
python setup.py install
export CLUSTER_ID='test'

# Run Pytest
python -m pytest --junitxml=./test-reports/coverage.xml
