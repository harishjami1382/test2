#!/bin/bash -x
source /usr/lib/hustler/bin/qubole-bash-lib.sh
source /etc/profile.d/airflow.sh # Since this file is executed by cron, below env vars are not automatically available
# shellcheck disable=SC2116
AIRFLOW_LOG_DIR=$(echo "$AIRFLOW_LOG_DIR")
# shellcheck disable=SC2116
AIRFLOW_HOME=$(echo "$AIRFLOW_HOME")
BASEDIR="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

function activate_virtualenv(){
    # shellcheck disable=SC1090
    source "${BASEDIR}"/scripts/virtualenv.sh activate
}

function deactivate_virtualenv(){
    # shellcheck disable=SC1090
    source "${BASEDIR}"/scripts/virtualenv.sh deactivate
}


function setup_upload_log_cron() {
    # Finding files changed in last 90 minutes as periodicity of cron is 60 mins & uploading them on s3
    # Using s3cmd as hadoop do not provide a way to overwrite existing file
    # shellcheck disable=SC2006
    airflow_logs_location_config=`grep -r remote_base_log_folder ${AIRFLOW_HOME}/airflow.cfg`
    airflow_logs_location=${airflow_logs_location_config#*=}
    files_to_upload=$(find "${AIRFLOW_LOG_DIR}" -maxdepth 1 ! -name '*.gz' -type f \( -mmin -90 -o -empty \) | tr '\n' ' ')
    if [[ ! -z $files_to_upload ]]; then
        # shellcheck disable=SC2086
        if [ $PROVIDER == azure ]; then
            /usr/lib/hadoop2/bin/hadoop dfs -Dfs.azure.account.key.${AZURE_STORAGE_ACCOUNT}.blob.core.windows.net=${AZURE_STORAGE_ACCESS_KEY} -put -f ${files_to_upload} ${airflow_logs_location}/process_logs/instance_id_${CLUSTER_INST_ID}/
        elif [ $PROVIDER == gcp ]; then
            gsutil -m cp ${files_to_upload} ${airflow_logs_location}/process_logs/instance_id_${CLUSTER_INST_ID}/
        else
            s3cmd put -c /usr/lib/hustler/s3cfg $files_to_upload ${airflow_logs_location}/process_logs/instance_id_${CLUSTER_INST_ID}/
        fi
    fi
}

function setup_delete_scheduler_process_log_cron() {

    scheduler_location_config=`grep -r child_process_log_directory ${AIRFLOW_HOME}/airflow.cfg`
    scheduler_log_location=${scheduler_location_config#*=}

    child_process_log_rotation_days_config=`grep -r child_process_log_rotation_days ${AIRFLOW_HOME}/airflow.cfg`
    days_buffer=${child_process_log_rotation_days_config#*=}

    log_date_to_be_deleted=`date -d "-${days_buffer} day" "+%Y-%m-%d"`
    rm -rf ${scheduler_log_location}/${log_date_to_be_deleted}
}

function airflow_idle_time_check() {
    sql_alchemy_conn=`grep -r sql_alchemy_conn ${AIRFLOW_HOME}/airflow.cfg`
    connection_string=${sql_alchemy_conn#*=}
    activate_virtualenv
    python ${AIRFLOW_HOME}/airflow/qubole_assembly/airflow_idle_time_check.py ${connection_string}
    deactivate_virtualenv
}

function airflow_sync_from_remote() {
    if [ $SYNC_TYPE == git ]
    then
        echo "returning as sync type is git"
        return 0
    fi

    if [ -z "$SYNC_LOCATION" ]
    then
        remote_location_string=`grep -r remote_base_log_folder ${AIRFLOW_HOME}/airflow.cfg`
        remote_location=${remote_location_string#*=}
    else
        remote_location=${SYNC_LOCATION}
    fi

    if [ $PROVIDER == azure ]; then
        /usr/lib/hadoop2/bin/hadoop dfs -Dfs.azure.account.key.${AZURE_STORAGE_ACCOUNT}.blob.core.windows.net=${AZURE_STORAGE_ACCESS_KEY} -get -f ${remote_location}/$1/* ${AIRFLOW_HOME}/$1/
    elif [ "$PROVIDER" == gcp ]; then
        # shellcheck disable=SC2086
        gsutil -m  cp -R "${remote_location}"/"$1"/* ${AIRFLOW_HOME}/$1/
    else
        # shellcheck disable=SC2086
        s3cmd sync -c /usr/lib/hustler/s3cfg ${remote_location}/$1/ ${AIRFLOW_HOME}/$1/
    fi

    activate_virtualenv
    airflow sync_perm
    deactivate_virtualenv
}

function update_sync_location() {
    activate_virtualenv
    # shellcheck disable=SC2086
    python ${AIRFLOW_HOME}/airflow/qubole_assembly/python_scripts/dag_sync_location_util.py >> "${AIRFLOW_LOG_DIR}"/sync_cron.log 2>&1
    chown -R airflow "${AIRFLOW_LOG_DIR}"/sync_cron.log
    deactivate_virtualenv
}

case "$1" in
  "setup_upload_log_cron" )
    setup_upload_log_cron
    ;;
  "setup_delete_scheduler_process_log_cron" )
    setup_delete_scheduler_process_log_cron
    ;;
  "airflow_idle_time_check" )
    airflow_idle_time_check
    ;;
  "airflow_sync_dags_from_remote" )
    airflow_sync_from_remote dags  >> "${AIRFLOW_LOG_DIR}"/sync_dags_cron.log 2>&1
    ;;
  "update_sync_location" )
    update_sync_location
    ;;
  "airflow_sync_plugins_from_remote" )
    airflow_sync_from_remote plugins >> "${AIRFLOW_LOG_DIR}"/sync_plugins_cron.log 2>&1
    ;;
  * )
    echo "Invalid argument passed"
    exit 1
    ;;
esac
