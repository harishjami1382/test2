import os
import subprocess

from airflow.exceptions import AirflowException
from airflow import configuration as conf


def backup_folder_exists():
    import commands
    remote_base_path = conf.get('core', 'REMOTE_BASE_LOG_FOLDER')
    if not remote_base_path.startswith('s3://'):
        raise AirflowException("There seems to be some problem with your defloc location")
    remote_loc = remote_base_path + '/dags_backup/'
    execute_cmd = 's3cmd ls -c /usr/lib/hustler/s3cfg {} | wc -l'.format(remote_loc)
    resp = commands.getoutput(execute_cmd)
    if resp != '0':
        return True
    return False


def untar_and_save_dags(tempDir):
    # import tarfile
    import commands
    airflow_home = os.environ['AIRFLOW_HOME']
    if not os.path.exists(airflow_home + "/dags"):
        os.makedirs(airflow_home + "/dags")
    cmd = "tar -vxzf {}/dags.tar.gz -C {}/dags/".format(tempDir, airflow_home)
    commands.getoutput(cmd=cmd)
    # tar = tarfile.open(tempDir + '/dags.tar.gz')
    # tar.extractall(path = airflow_home + "/dags/")
    # for member in tar.getmembers():
    #     tar.extract(member, airflow_home + '/dags/')


def pull_from_s3(remote_loc, localDir):
    execute_cmd = ['s3cmd', 'get', '-c', '/usr/lib/hustler/s3cfg']
    execute_cmd.extend([remote_loc, localDir + '/', '--force'])
    process = subprocess.Popen(execute_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.wait()


def push_to_s3(dags_folder):
    remote_base_path = conf.get('core', 'REMOTE_BASE_LOG_FOLDER')
    remote_loc = remote_base_path + '/dags_backup/'
    execute_cmd = ['s3cmd', 'put', '-c', '/usr/lib/hustler/s3cfg']
    execute_cmd.extend(['dags.tar.gz', remote_loc])

    process = subprocess.Popen(execute_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.wait()
