try:
    import ConfigParser
except:
    import configparser as ConfigParser
import traceback
import sys
import os
from optparse import OptionParser
import base64
import subprocess


def handle_specific_config(overrides_map, options):

    # Handle sqlalchemy settings
    use_cluster_datastore = False
    core_settings = overrides_map.get('core', {})
    logging_settings = overrides_map.get('logging', {})


    if not 'remote_base_log_folder' in logging_settings or logging_settings['remote_base_log_folder'] is None or logging_settings['remote_base_log_folder'] == "":
        logging_settings['remote_base_log_folder'] = os.getenv('AIRFLOW_LOGS_LOCATION', "")
        if 'logging' not in overrides_map.keys():
            overrides_map['logging'] = logging_settings


    cluster_id = os.getenv('CLUSTER_ID', "")
    qubole_base_url = os.getenv('QUBOLE_BASE_URL', "api.qubole.com")
    if not 'sql_alchemy_conn' in core_settings or core_settings['sql_alchemy_conn'] is None or core_settings['sql_alchemy_conn'] == "":

        core_settings['sql_alchemy_conn'] = "postgresql://root:" + cluster_id + "@localhost:5432/airflow"
        use_cluster_datastore = True

    # Handle webserver settings
    web_server_port = '8080'
    if not 'webserver' in overrides_map:
        overrides_map['webserver'] = {}

    # user controlled port will be bad idea, keeping it 8080 only
    overrides_map['webserver']['web_server_port'] = web_server_port
    if not 'base_url' in overrides_map['webserver']:
        # Ideally we should not accpet any overrides for base url, this is temporary as sometimes we have to manually
        # setup multi-node cluster using various one-node clusters.
        overrides_map['webserver']['base_url'] = qubole_base_url + "/airflow-rbacwebserver-" + cluster_id

    # Handle celery executor settings
    default_broker_url = 'amqp://guest:guest@localhost:5672/'
    use_cluster_broker_airflow = True
    use_celery_airflow = True

    if overrides_map.get('core', {}).get('executor', None) == 'CeleryExecutor':
        # Executor type will always be there because we will set it in recommended config to use celery broker
        if 'celery' in overrides_map and 'broken_url' in overrides_map['celery']:  # Means user is hosting his own messaging broker
            use_cluster_broker_airflow = False
    else: # Implies user does not want to use celery executor
        use_cluster_broker_airflow = False
        use_celery_airflow = False

    if use_celery_airflow:
        if not 'celery' in overrides_map:
            overrides_map['celery'] = {}

        if use_cluster_broker_airflow:
            overrides_map['celery']['broker_url'] = default_broker_url # Default broker config on machine

        if 'result_backend' not in overrides_map['celery']:
            # Reason for using sql alchemy for result backend: QBOL-5589
            sql_alchemy_conn = overrides_map['core']['sql_alchemy_conn']
            overrides_map['celery']['result_backend'] = 'db+' + sql_alchemy_conn

        if 'celeryd_concurrency' in overrides_map['celery']:
            overrides_map['celery']['worker_concurrency'] = overrides_map['celery']['celeryd_concurrency']
            del overrides_map['celery']['celeryd_concurrency']

    overrides_map['webserver']['rbac'] = False
    return (use_cluster_broker_airflow, use_celery_airflow, use_cluster_datastore)


def setup_scheduler_child_process_directory_and_cron(overrides_map):
    if not 'scheduler' in overrides_map:
        overrides_map['scheduler'] = {}

    if not 'child_process_log_directory' in overrides_map['scheduler']:
        overrides_map['scheduler']['child_process_log_directory'] = '{0}/scheduler_task_logs'.format(os.getenv('AIRFLOW_LOG_DIR', '/media/ephemeral0/logs/airflow'))

    if not 'child_process_log_rotation_days' in overrides_map['scheduler']:
        overrides_map['scheduler']['child_process_log_rotation_days'] = '2'


def setup_logs_symlink(final_config):
    logs_folder = final_config['logging']['base_log_folder']
    symlink_folder = "{0}/logs".format(final_config['core']['airflow_home'])
    if logs_folder != symlink_folder:
        symlink_command = ["ln", "-s", logs_folder, symlink_folder]
        process = subprocess.Popen(symlink_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        std, err = process.communicate()

        if err != '':
            print("An error occured while creating symlink: {0}".format(err))


def main():
    optparser = OptionParser()

    optparser.add_option("--airflow-overrides", default="", help="Airflow config overrides")
    optparser.add_option("--master-public-dns", default=None, help="Master Public DNS of the cluster")
    optparser.add_option("--airflow-home", help="Airflow Home")
    optparser.add_option("--airflow-env-var-file", help="Airflow Environment File Location")

    (options, args) = optparser.parse_args()

    if options.airflow_home is None:
        optparser.error('--airflow-home is mandatory')

    if options.airflow_env_var_file is None:
        optparser.error('--airflow-env-var-file is mandatory')

    # Overall aim is to merge the overrides by user/recommended with the ones present as default in airflow config.

    # Read config from Airflow Config file present at AIRFLOW_HOME
    config = ConfigParser.RawConfigParser()
    airflow_config_file_path = os.path.join(options.airflow_home , 'airflow.cfg')
    config.read(airflow_config_file_path)
    config_sections = config.sections()

    # Parse the overrides in the form section1.key1=value1!section2.key2=value2..
    # Store them in a map where key is section name and value is
    # a map with key value pairs of that section
    airflow_overrides = options.airflow_overrides
    overrides = airflow_overrides.split('!')
    overrides_map = {}
    for override in overrides:
        kv = override.split('.', 1)
        if len(kv) != 2:
            continue
        section = kv[0]
        prop_val = kv[1]
        kv = prop_val.split('#', 1)
        if len(kv) != 2:
            continue
        if not section in overrides_map:
            overrides_map[section] = {}
        overrides_map[section][kv[0]] = base64.b64decode(kv[1]).decode('utf-8')

    (use_cluster_broker_airflow, use_celery_airflow, use_cluster_datastore) = handle_specific_config(overrides_map, options)
    setup_scheduler_child_process_directory_and_cron(overrides_map)
    # Get all sections by combining sections in overrides and config file
    overrides_sections = list(overrides_map.keys())
    sections = set(config_sections + overrides_sections)
    final_config = {}

    # Now it's time to merge configurations of both airflow config file and overrides
    for section in sections:
        config_items = {}
        if config.has_section(section):
            # config.items(section) is of the form [(key1, value1), (key2, value2)..] and then converted to dict.
            config_items = dict(config.items(section))

        override_items = {}
        if section in overrides_map:
            override_items = overrides_map[section]

        # Merge the 2 maps
        # Priority overrides > default config
        final_section_config = dict(list(config_items.items()) + list(override_items.items()))
        final_config[section] = final_section_config

    # Finally we just reset the config object to have all sections with required options
    for section in final_config.keys():
        if not config.has_section(section):
            config.add_section(section)
        for option in final_config[section].keys():
            config.set(section, option, final_config[section][option])

    # Now dump the config again in the airflow config file
    with open(airflow_config_file_path, 'w') as airflow_config_file:
        config.write(airflow_config_file)

    airflow_env_var_file_path = options.airflow_env_var_file
    setup_logs_symlink(final_config)
    newFileData = ""
    for line in open(airflow_env_var_file_path, 'r'):
        if "export USE_CELERY_AIRFLOW=" in line or "export USE_CLUSTER_BROKER_AIRFLOW=" in line or "export USE_CLUSTER_DATASTORE=" in line:
            line = ""
        newFileData += line
    with open(airflow_env_var_file_path, 'w') as airflow_env_var_file:
        airflow_env_var_file.write(newFileData)

    with open(airflow_env_var_file_path, 'a') as airflow_env_var_file:
        airflow_env_var_file.write("export USE_CELERY_AIRFLOW=" + str(use_celery_airflow) + "\n")
        airflow_env_var_file.write("export USE_CLUSTER_BROKER_AIRFLOW=" + str(use_cluster_broker_airflow) + "\n")
        airflow_env_var_file.write("export USE_CLUSTER_DATASTORE=" + str(use_cluster_datastore) + "\n")

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
