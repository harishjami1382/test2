#!/usr/bin/env bash
set -e

function create_virtualenv() {
    virtualenv ${VIRTUAL_ENV_LOC} -p python2.7
}

function install_requirements() {
    source ${VIRTUAL_ENV_LOC}/bin/activate
    pip install pip==18.0
    pip install -r ${DIR}/requirements.txt --ignore-installed
    deactivate
}

function setup_virtualenv() {
    if [ ! -d "$VIRTUAL_ENV_LOC" ]; then
        create_virtualenv
    fi
    install_requirements
}

VIRTUAL_ENV_LOC="/usr/lib/virtualenv/airflow/1.10.0"
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
setup_virtualenv
