#!/bin/bash -x
airflow_source_dir="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source /usr/lib/hustler/bin/qubole-bash-lib.sh

function setup_airflow() {
  setup_env_variables
  store_env_variables_in_envfile
  setup_airflow_home
  install_airflow
  sleep 2 # Add this to ensure that all the env variables are set before proceeding to configuring airflow
  configure_airflow
  setup_airflow_directories
  remove_entry_from_ssh_config
  setup_remote_dirs
  #This is required to overcome the shortcoming of OS version, where no dags are detected if dags folder is empty
  add_dag_to_dags_folder
  start_airflow
  sleep 10 # Adding a sleep of 10 seconds so that services are up by the time monitoring kicks off.
  start_monit_airflow
  config_monit_httpd
  setup_alerting_cron
  setup_logrotation_cron
}

function activate_virtualenv(){
    source ${airflow_source_dir}/scripts/virtualenv.sh activate
}

function deactivate_virtualenv(){
    source ${airflow_source_dir}/scripts/virtualenv.sh deactivate
}


function refresh_airflow() {
  setup_env_variables
  cleanup_virtualenv
  if [[ ${AIRFLOW_OVERRIDES} != "" ]]; then
    configure_airflow
  fi
  start_refresh_services
}

function cleanup_virtualenv() {
  activate_virtualenv
  yes | pip uninstall simplejson # Remove this after itsdangerous==2.0.0 is released
  deactivate_virtualenv
}

function setup_env_variables() {
  AIRFLOW_LOGS_LOCATION=$DEFAULT_REMOTE_LOCATION/airflow/$CLUSTER_ID
  AIRFLOW_MONIT_FILE=${airflow_source_dir}/monit.sh
  AIRFLOW_VIRTUALENV_LOC=/usr/lib/virtualenv/airflow/1.10.0

  if [[ `nodeinfo quboled_env_python_version` == 3* ]]; then
    ENV_LOCATION=$(nodeinfo quboled_env_python_package_name)
    if [[ `nodeinfo quboled_env_python_version` == 3.7* ]]; then
        AIRFLOW_VIRTUALENV_LOC=/usr/lib/environs/${ENV_LOCATION}
    elif [[ `nodeinfo quboled_env_python_version` == 3.5* ]]; then
        AIRFLOW_VIRTUALENV_LOC=/usr/lib/envs/${ENV_LOCATION}
    fi
  fi

  AIRFLOW_SCHEDULER_PID=${AIRFLOW_HOME}/scheduler.pid
  AIRFLOW_WEBSERVER_PID=${AIRFLOW_HOME}/webserver.pid
  AIRFLOW_RABBITMQ_PID=${AIRFLOW_HOME}/rabbitmq.pid
  AIRFLOW_WORKER_PID=${AIRFLOW_HOME}/worker.pid
  AIRFLOW_LOG_DIR=/media/ephemeral0/logs/airflow
  AIRFLOW_WEBSERVER_PROXY_URI=airflow-rbacwebserver-${CLUSTER_ID}
}

function setup_airflow_home() {
  ln -s ${AIRFLOW_PACKAGE_DIR}/airflow-${AIRFLOW_VERSION}/airflow /usr/lib/airflow
}


# Put these packages in the AMI to improve cluster startup time.
function install_dependency() {
  if [[ `nodeinfo quboled_env_python_version` == 3* ]]; then
    conda install -c bioconda mysqlclient
    if [[ `nodeinfo quboled_env_python_version` == 3.7* ]]; then
        conda install -c conda-forge mysql-connector-c
    fi
    pip install celery==4.4.2
    pip install qds-sdk==1.16.0
    ln -s /var/lib/mysql/mysql.sock /tmp/mysql.sock

    if [[ "${PROVIDER}" == "gcp" ]]; then
        pip install -r ${airflow_source_dir}/cloud_requirements/gcp.txt
    fi
  fi
}

function install_airflow() {

  activate_virtualenv
  install_dependency
  pushd ${AIRFLOW_HOME}
  pushd airflow

  # install dependencies
  pip install -e .

  # install airflow
  python setup.py install
  yes | pip uninstall simplejson # Remove this after itsdangerous==2.0.0 is released
  popd
  popd
  deactivate_virtualenv
}

function store_env_variables_in_envfile() {
  # Setting AIRFLOW_HOME environment variable at environment level
  # so that all users have access to it on permanent basis, e.g ec2-user

  # Also setting C_FORCE_ROOT, this is used to enable celery to run in root mode else it throws out error
  # This is not recommeded though - http://docs.celeryproject.org/en/latest/faq.html#is-it-safe-to-run-celery-worker-as-root
  cat >> /etc/profile.d/airflow.sh <<EOF
export AIRFLOW_HOME=$AIRFLOW_HOME
export C_FORCE_ROOT=true
export CLUSTER_ID=$CLUSTER_ID
export QUBOLE_BASE_URL=$QUBOLE_BASE_URL
export QUBOLE_CLUSTER_API_TOKEN=$QUBOLE_CLUSTER_API_TOKEN
export AIRFLOW_LOGS_LOCATION=$AIRFLOW_LOGS_LOCATION
export AIRFLOW_LOG_DIR=$AIRFLOW_LOG_DIR
export AIRFLOW_ENV_VAR_FILE=$AIRFLOW_ENV_VAR_FILE
export PROVIDER=$PROVIDER
export AIRFLOW__QUBOLE__PROVIDER=$PROVIDER
export AIRFLOW_VIRTUALENV_LOC=$AIRFLOW_VIRTUALENV_LOC
export CLUSTER_INST_ID=$CLUSTER_INST_ID
export AIRFLOW_WEBSERVER_PROXY_URI=$AIRFLOW_WEBSERVER_PROXY_URI
export AIRFLOW_USER_HOME=/home/airflow
export IS_AL2_AMI=$IS_AL2_AMI
export SYNC_LOCATION=
export SYNC_TYPE=
export VENV=$AIRFLOW_HOME/airflow/qubole_assembly/scripts/virtualenv.sh
export SERVER=$AIRFLOW_HOME/airflow/qubole_assembly/scripts/server.go
EOF
  activate_virtualenv
  source ${AIRFLOW_ENV_VAR_FILE}
  deactivate_virtualenv
}

function configure_airflow() {
  echo "Configuring Airflow"
  # Also setting C_FORCE_ROOT, this is used to enable celery to run in root mode else it throws out error
  # This is not recommeded though - http://docs.celeryproject.org/en/latest/faq.html#is-it-safe-to-run-celery-worker-as-root

  # Initialize the default airflow config at AIRFLOW HOME location
  activate_virtualenv
  airflow version # Sample command to initiate the config
  python ${airflow_source_dir}/configure_airflow.py "--airflow-overrides=${AIRFLOW_OVERRIDES}" "--master-public-dns=${MASTER_PUBLIC_DNS}" "--airflow-home=${AIRFLOW_HOME}" "--airflow-env-var-file=${AIRFLOW_ENV_VAR_FILE}"
  source ${AIRFLOW_ENV_VAR_FILE}
  deactivate_virtualenv
}

function start_refresh_services() {
    if [[ -f ${AIRFLOW_HOME}/webserver.pid ]]; then
        sudo monit restart worker
        sudo monit restart webserver
        create_restart_scheduler_file
    fi
}

function create_restart_scheduler_file() {
  touch $AIRFLOW_HOME/scheduler.restart
}

function setup_airflow_directories(){
    echo "Setting up Airflow Directories"

    mkdir -p -m 777 ${AIRFLOW_HOME}/dags
    mkdir -p -m 777 ${AIRFLOW_HOME}/plugins
    mkdir -p -m 777 ${AIRFLOW_LOG_DIR}
    mkdir -m 700 ${AIRFLOW_USER_HOME}

    echo "Setting up files to store PID"
    touch ${AIRFLOW_HOME}/scheduler.pid
    touch ${AIRFLOW_HOME}/webserver.pid
    touch ${AIRFLOW_HOME}/parent_webserver.pid
    touch ${AIRFLOW_HOME}/worker.pid

    echo "Changing owners of Airflow Directories"
    chown -R airflow ${AIRFLOW_HOME}
    AIRFLOW_HOME_SYMLINK=$(readlink ${AIRFLOW_HOME})
    chown -R airflow ${AIRFLOW_HOME_SYMLINK}
    chown -R airflow ${AIRFLOW_LOG_DIR}/*
    chown -R airflow ${AIRFLOW_HOME}/*
    chown -R airflow ${AIRFLOW_USER_HOME}
}

function remove_entry_from_ssh_config(){
    if [[ $IS_AL2_AMI == "true" ]]; then
        sed -i -e 's/DenyUsers airflow//g' /etc/ssh/ssh_config
        sed -i -e 's/DenyUsers airflow//g' /etc/ssh/sshd_config
        echo -e "\n" >> /etc/ssh/sshd_config
        echo "AllowUsers airflow" >> /etc/ssh/sshd_config
        sudo service sshd restart
    fi
}

function add_dag_to_dags_folder(){
    echo "Adding a dag  from example dags to dags folder"
    cp $AIRFLOW_HOME/airflow/airflow/example_dags/tutorial.py $AIRFLOW_HOME/dags/
    chown -R airflow $AIRFLOW_HOME/dags/*
}

function start_airflow() {
  echo "Starting Airflow"
  #source ${airflow_source_dir}/start_airflow.sh "${AIRFLOW_MONIT_PID}" "${AIRFLOW_LOG_DIR}" "${CLUSTER_ID}"
  source ${airflow_source_dir}/start_airflow.sh start all
}

function start_monit_airflow(){
  echo "Setting up Airflow Monit"

  setup_scheduler_monit

  setup_webserver_monit

  use_celery_airflow=$(echo $USE_CELERY_AIRFLOW)
  use_cluster_broker_airflow=$(echo $USE_CLUSTER_BROKER_AIRFLOW)

  if [[ "$use_cluster_broker_airflow" == "True" ]]; then
    setup_rabbitmq_monit
  fi

  if [[ "$use_celery_airflow" == "True" ]]; then
    setup_worker_monit
  fi

  setup_exim_monit

  service monit restart
}

function config_monit_httpd() {

# allow monit dashboard access from all IP addresses
echo "set httpd port 2812 and
  use address 0.0.0.0
  allow 0.0.0.0/0.0.0.0
  allow airflow:'${CLUSTER_ID}'" >> /etc/monitrc
monit reload
}

function setup_scheduler_monit(){

  # Configure airflow scheduler to run with monit.
  cat > /etc/monit.d/airflow-scheduler.cfg<<EOF
set daemon 30
set logfile /var/log/monit.log

check process scheduler with pidfile $AIRFLOW_SCHEDULER_PID
   # Restarting as we want to do some cleanup before starting any service
   start program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh restart scheduler'"
        as uid airflow and gid airflow
   stop program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh stop scheduler'"
        as uid airflow and gid airflow
   if 5 restarts within 5 cycles then timeout
EOF

}

function setup_webserver_monit(){

  # Configure airflow webserver to run with monit.
  cat > /etc/monit.d/airflow-webserver.cfg<<EOF
set daemon 30
set logfile /var/log/monit.log

check process webserver with pidfile $AIRFLOW_WEBSERVER_PID
   # Restarting as we want to do some cleanup before starting any service
   start program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh restart webserver'"
        as uid airflow and gid airflow
   stop program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh stop webserver'"
        as uid airflow and gid airflow
   if 5 restarts within 5 cycles then timeout
EOF

}

function setup_rabbitmq_monit(){

  # Configure airflow webserver to run with monit.
  cat > /etc/monit.d/airflow-rabbitmq.cfg<<EOF
set daemon 30
set logfile /var/log/monit.log

check process rabbitmq with pidfile $AIRFLOW_RABBITMQ_PID
   # Restarting as we want to do some cleanup before starting any service
   start program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh restart rabbitmq'"
   stop program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh stop rabbitmq'"
   if 5 restarts within 5 cycles then timeout
EOF

}

function setup_worker_monit(){

  # Configure airflow worker to run with monit.
  cat > /etc/monit.d/airflow-worker.cfg<<EOF
set daemon 30
set logfile /var/log/monit.log

check process worker with pidfile $AIRFLOW_WORKER_PID
   # Restarting as we want to do some cleanup before starting any service
   start program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh restart worker'"
        as uid airflow and gid airflow
   stop program = "/bin/bash -c 'source ${AIRFLOW_ENV_VAR_FILE} && ${airflow_source_dir}/start_airflow.sh stop worker'"
        as uid airflow and gid airflow
   if 5 restarts within 5 cycles then timeout
EOF

}

function setup_exim_monit(){

   # Configure exim to run with monit.

if [[ $PROVIDER == aws ]] && [[ $IS_AL2_AMI != "true" ]]; then
    cat > /etc/monit.d/airflow-exim.cfg<<EOF
set daemon 30
set logfile /var/log/monit.log

    check process exim
        matching "/usr/sbin/exim"
        start program = "/etc/init.d/exim start"
        stop program = "/etc/init.d/exim stop"
        if 10 restarts within 10 cycles then timeout
EOF
else
    cat > /etc/monit.d/airflow-exim.cfg<<EOF
set daemon 30
set logfile /var/log/monit.log

    check process exim
        matching "/usr/sbin/exim"
        start program = "/bin/bash -c 'systemctl start exim'"
        stop program = "/bin/bash -c ' systemctl stop exim'"
        if 10 restarts within 10 cycles then timeout
EOF
fi

}

function setup_logrotation_cron(){

  # Airflow Logrotation Configuration file, run on daily basis
  cat > /etc/logrotate.d/airflow<<EOF
/media/ephemeral0/logs/airflow/*.log {
rotate 5
daily
size 100M
dateext
dateformat -%Y-%m-%d_%s
compress
missingok
delaycompress
copytruncate
maxage 10
}
EOF
}

function setup_alerting_cron(){

touch $AIRFLOW_HOME/services_heartbeats.pkl

crontab -l | { cat; echo "*/3 * * * * source /etc/profile.d/airflow.sh; source ${BASEDIR}/scripts/virtualenv.sh activate; python ${airflow_source_dir}/god.py >> ${AIRFLOW_LOG_DIR}/health_checks.log; ${BASEDIR}/scripts/virtualenv.sh deactivate"; } | sort -u | crontab -


}

function setup_remote_dirs(){
    remote_location_string=`grep -r remote_base_log_folder ${AIRFLOW_HOME}/airflow.cfg`
    remote_location=${remote_location_string#*=}
    remote_location=$(echo "${remote_location}" | xargs)
    if [ $PROVIDER == azure ]; then
        /usr/lib/hadoop2/bin/hadoop dfs -Dfs.azure.account.key.${AZURE_STORAGE_ACCOUNT}.blob.core.windows.net=${AZURE_STORAGE_ACCESS_KEY} -mkdir -p ${remote_location}/dags ${remote_location}/plugins ${remote_location}/dag_logs ${remote_location}/process_logs/instance_id_${CLUSTER_INST_ID}
    else
        hadoop dfs -mkdir -p ${remote_location}/dags ${remote_location}/plugins ${remote_location}/dag_logs ${remote_location}/process_logs/instance_id_${CLUSTER_INST_ID}
    fi
}

case "$1" in
  "setup" )
    AIRFLOW_HOME=$2
    AIRFLOW_ENV_VAR_FILE=$3
    AIRFLOW_OVERRIDES=$4
    CLUSTER_ID=$5
    AIRFLOW_VERSION=$6
    AIRFLOW_PACKAGE_DIR=$7
    export PROVIDER=$8 # Figure out a way to get the correct cloud here
    CLUSTER_INST_ID=`nodeinfo cluster_inst_id`
    export SLUGIFY_USES_TEXT_UNIDECODE=yes

    if [ $PROVIDER == aws ]; then
      source /usr/lib/hustler/bin/nodeinfo_src.sh
      MASTER_PUBLIC_DNS=`nodeinfo master_public_dns_or_private_ip`
      QUBOLE_BASE_URL=`nodeinfo qubole_base_url`
      QUBOLE_CLUSTER_API_TOKEN=`nodeinfo qubole_cluster_api_token`
      DEFAULT_REMOTE_LOCATION=`nodeinfo s3_default_location`
      IS_AL2_AMI="false"
      IMAGE_GENERATION=`nodeinfo image_generation`
      if [[ "$IMAGE_GENERATION" -ge "2" ]]; then
        IS_AL2_AMI="true"
      fi
    else
      MASTER_PUBLIC_DNS="${9}"
      QUBOLE_BASE_URL="${10}"
      QUBOLE_CLUSTER_API_TOKEN="${11}"
      DEFAULT_REMOTE_LOCATION="${12}"
      python ${airflow_source_dir}/setup_cloud_keys.py
    fi
    setup_airflow
    ;;
  "refresh" )
    AIRFLOW_OVERRIDES=$2
    refresh_airflow
    ;;
  * )
    echo "only setup and refresh are supported"
    exit 1
    ;;
esac
