import os
try:
    from json import json
except ImportError:
    import json

is_airflow_on_k8s = os.getenv("AIRFLOW_ON_K8s", 0) in [1, "1"]


def restart_scheduler():
    airflow_home = os.getenv("AIRFLOW_HOME", "/usr/lib/airflow")
    if os.path.exists(airflow_home + "/scheduler.restart"):
        try:
            os.remove(airflow_home + "/scheduler.restart")
            return True
        except:
            pass


def delete_scheduler_check_file(check_type):
    airflow_home = os.getenv("AIRFLOW_HOME", "/usr/lib/airflow")
    k8s_folder = os.getenv("AIRFLOW_SHARED_DIRECTORY", "/shared")
    try:
        os.remove(airflow_home + "/scheduler.{}".format(check_type))
        return True
    except:
        pass

    if is_airflow_on_k8s:
        try:
            os.remove(k8s_folder + "/scheduler.{}".format(check_type))
            return True
        except:
            pass


def check_refresh_file_exists():
    if is_airflow_on_k8s:
        check_folder = os.getenv("AIRFLOW_SHARED_DIRECTORY", "/shared")
    else:
        check_folder = os.getenv("AIRFLOW_HOME", "/usr/lib/airflow")
    return os.path.exists("{}/scheduler.refresh".format(check_folder))


def read_from_root_config_json(key_array=[]):
    try:
        config = json.load(open('/root/config.json', "r+"))
        if key_array:
            value = config
            for key in key_array:
                value = value[key]
            return value
        else:
            return config
    except:
        return None



