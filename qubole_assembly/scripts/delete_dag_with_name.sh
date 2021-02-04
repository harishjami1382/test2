#!/bin/bash -x
set -e
source /usr/lib/hustler/bin/qubole-bash-lib.sh
source /etc/profile.d/airflow.sh
AIRFLOW_HOME=$(echo $AIRFLOW_HOME)
BASEDIR="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
FILENAME=$1

function activate_virtualenv(){
    source ${BASEDIR}/virtualenv.sh activate
}

function deactivate_virtualenv(){
    source ${BASEDIR}/virtualenv.sh deactivate
}

function delete_dag_from_local(){
    rm -f ${AIRFLOW_HOME}/dags/${FILENAME}
}

function delete_dag_from_remote(){

    if [ -z "$SYNC_LOCATION" ]
    then
        remote_location_string=`grep -r remote_base_log_folder ${AIRFLOW_HOME}/airflow.cfg`
        remote_location=${remote_location_string#*=}
    else
        remote_location=${SYNC_LOCATION}
    fi

    if [ $PROVIDER == azure ]; then
        /usr/lib/hadoop2/bin/hadoop dfs -Dfs.azure.account.key.${AZURE_STORAGE_ACCOUNT}.blob.core.windows.net=${AZURE_STORAGE_ACCESS_KEY} -rm -f ${remote_location}/dags/${FILENAME}
    elif [ $PROVIDER == gcp ]; then
        gsutil rm ${remote_location}/dags/${FILENAME}
    else
        s3cmd del -c /usr/lib/hustler/s3cfg ${remote_location}/dags/${FILENAME}
    fi
}

delete_dag_from_local
delete_dag_from_remote
