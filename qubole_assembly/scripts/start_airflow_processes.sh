#!/bin/bash -x

function start_all() {
start_worker
start_scheduler
start_webserver
setup_crons
}

function start_scheduler() {

sudo chown -R airflow ${AIRFLOW_LOG_DIR}/scheduler_task_logs/
nohup airflow scheduler &>> ${AIRFLOW_LOG_DIR}/scheduler.log & echo $! > ${AIRFLOW_SCHEDULER_PID}

}

function start_webserver() {

#Starting webserver in debug mode to enable auto refresh of updated/new dags
nohup airflow webserver -p8080 &>> ${AIRFLOW_LOG_DIR}/webserver.log &

# Fetching the child process id, the child process is the actual webapp which runs on the machine
# so we need to monitor the child process, the parent is just shell command, even if it dies child still continue to run
# and the output stream continues to log in log file. Also we will have to add wait for child process to start

pid=$(echo $!)
echo "$pid" > ${AIRFLOW_PARENT_WEBSERVER_PID}
cpid=""
i="0"
echo "Parent Process Id of Webserver" "$pid"
while [ $i -lt 20 ]
    do
        cpid=$(echo $(pgrep -P $pid))
        echo "Child process id" "$cpid"
        if [[ ! -z $cpid ]]; then
            break
        fi

    # Generally it takes 3 seconds
    sleep 1
    i=$[$i+1]
done

echo "$cpid" > ${AIRFLOW_WEBSERVER_PID}
if [[ ! -z $cpid ]]; then
    echo "Webserver startup successful"
else
    echo "Webserver startup failed, child process is empty"
fi

}

function start_worker() {

if [[ "$use_celery_airflow" == "True" ]]; then
    FLOWER_URL_PREFIX=airflow-celery-${CLUSTER_ID}
    export FLOWER_URL_PREFIX=$FLOWER_URL_PREFIX
    # Forking these commands as child processes(using & at the end) because these services will keep running indefinitely
    # so do not want parent process to wait for them else subsequent commands won't be triggered
    # This is not done for initdb command because subsequent commands should not start until the tables are not created else they may fail
    nohup airflow celery worker &>> ${AIRFLOW_LOG_DIR}/celery-worker.log & echo $! > ${AIRFLOW_WORKER_PID}
    nohup airflow celery flower &>> ${AIRFLOW_LOG_DIR}/flower.log &
fi

}

function setup_crons() {

# Setup a cron on hourly basis
crontab -l | { cat; echo "0 * * * *  /bin/bash ${airflow_source_dir}/../setup_crons.sh setup_upload_log_cron"; } | sort -u | crontab -

crontab -l | { cat; echo "4 0 * * *  /bin/bash ${airflow_source_dir}/../setup_crons.sh setup_delete_scheduler_process_log_cron"; } | sort -u | crontab -

# crontab -l | { cat; echo "4 0 * * *  source ${airflow_source_dir}/setup_crons.sh airflow_idle_time_check"; } | sort -u | crontab -

crontab -l | { cat; echo "*/5 * * * *  /bin/bash ${airflow_source_dir}/../setup_crons.sh airflow_sync_dags_from_remote"; } | sort -u | crontab -

crontab -l | { cat; echo "*/5 * * * *  /bin/bash ${airflow_source_dir}/../setup_crons.sh airflow_sync_plugins_from_remote"; } | sort -u | crontab -

crontab -l | { cat; echo "*/5 * * * *  /bin/bash ${airflow_source_dir}/../setup_crons.sh update_sync_location"; } | sort -u | crontab -
}

function activate_virtualenv(){
    source ${BASEDIR}/virtualenv.sh activate
}

function deactivate_virtualenv(){
    source ${BASEDIR}/virtualenv.sh deactivate
}

SERVICE=$1
BASEDIR="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
activate_virtualenv
source /usr/lib/hustler/bin/qubole-bash-lib.sh
source /etc/profile.d/airflow.sh
AIRFLOW_HOME=$(echo $AIRFLOW_HOME)
AIRFLOW_SCHEDULER_PID=${AIRFLOW_HOME}/scheduler.pid
AIRFLOW_WEBSERVER_PID=${AIRFLOW_HOME}/webserver.pid
AIRFLOW_PARENT_WEBSERVER_PID=${AIRFLOW_HOME}/parent_webserver.pid
AIRFLOW_RABBITMQ_PID=${AIRFLOW_HOME}/rabbitmq.pid
AIRFLOW_WORKER_PID=${AIRFLOW_HOME}/worker.pid
AIRFLOW_LOG_DIR=/media/ephemeral0/logs/airflow/
CLUSTER_ID=$(echo $CLUSTER_ID)
qubole_base_url=$(echo $QUBOLE_BASE_URL)
use_celery_airflow=$(echo $USE_CELERY_AIRFLOW)
use_cluster_broker_airflow=$(echo $USE_CLUSTER_BROKER_AIRFLOW)
airflow_source_dir="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
worker_child_pids=


case "${SERVICE}" in
  "all" )
    start_all
    ;;
  "scheduler" )
    start_scheduler
    ;;
  "webserver" )
    start_webserver
    ;;
  "worker" )
    start_worker
    ;;
  * )
    echo "only all, scheduler, webserver are supported"
    exit 1
    ;;
esac
deactivate_virtualenv



