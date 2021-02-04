#!/usr/bin/env bash
source /usr/lib/hustler/bin/qubole-bash-lib.sh
source /etc/profile.d/airflow.sh

function env_activate(){
  if [[ `nodeinfo quboled_env_python_version` == 3.7* ]]; then
    sub_string="e-"
    base_env="${AIRFLOW_VIRTUALENV_LOC//$sub_string/}"
    source ${base_env}/bin/activate ${AIRFLOW_VIRTUALENV_LOC}
  elif [[ `nodeinfo quboled_env_python_version` == 3.5* ]]; then
    source $AIRFLOW_VIRTUALENV_LOC/bin/activate ${AIRFLOW_VIRTUALENV_LOC}
  else
    source $AIRFLOW_VIRTUALENV_LOC/bin/activate #for python2.7
  fi
}

function env_deactivate(){
  if [[ `nodeinfo quboled_env_python_version` == 3.5* ]]; then
    source deactivate
  elif [[ `nodeinfo quboled_env_python_version` == 3.7* ]]; then
    conda deactivate
  else
    deactivate
  fi
}

case "$1" in
  "activate" )
    env_activate
    ;;
  "deactivate" )
    env_deactivate
    ;;
  * )
    echo "Invalid argument passed"
    exit 1
    ;;
esac
