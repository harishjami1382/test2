# -*- coding: utf-8 -*-
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
import tempfile
import subprocess

from airflow.utils.log.file_task_handler import FileTaskHandler
from airflow.configuration import conf


class QDSTaskHandler(FileTaskHandler):
    """
    QDSTaskHandler is a python log handler that handles and reads
    task instance logs. It extends airflow FileTaskHandler and
    uploads to and reads from S3/Azure remote storage.
    """

    def __init__(self, base_log_folder, qds_log_folder, filename_template):
        super(QDSTaskHandler, self).__init__(base_log_folder, filename_template)
        self.remote_base = qds_log_folder
        self.log_relative_path = ''
        self.closed = False

    def set_context(self, ti):
        """
        Local location and remote location is needed to open and
        upload local log file to S3 remote storage.
        :param ti:
        """
        super(QDSTaskHandler, self).set_context(ti)
        self.log_relative_path = self._render_filename(ti, ti.try_number)

    def close(self):
        """
        Close and upload local log file to remote storage S3.
        """
        # When application exit, system shuts down all handlers by
        # calling close method. Here we check if logger is already
        # closed to prevent uploading the log to remote storage multiple
        # times when `logging.shutdown` is called.
        super(QDSTaskHandler, self).close()
        if self.closed or not self.log_relative_path:
            self.closed = True
            return

        local_loc = os.path.join(self.local_base, self.log_relative_path)
        remote_loc = os.path.join(self.remote_base, self.log_relative_path)
        provider = "kubernetes" if conf.getboolean("qubole", "K8S_RUNTIME") else os.environ.get('PROVIDER', "")
        if os.path.exists(local_loc):
            if provider == "kubernetes":
                execute_cmd = ['aws', 's3', 'cp']
                execute_cmd.extend([local_loc, remote_loc])
            elif provider == 'azure':
                # We have to do this because azure does not support colon in the file path
                self.log_relative_path = self.log_relative_path.replace(':', '.')
                execute_cmd = ['/usr/lib/hadoop2/bin/hadoop', 'dfs',
                               '-Dfs.azure.account.key.{}.blob.core.windows.net={}'.format(
                                   os.environ.get("AZURE_STORAGE_ACCOUNT"), os.environ.get("AZURE_STORAGE_ACCESS_KEY"))]
                execute_cmd.extend(
                    ["-copyFromLocal", "-f", local_loc, "{}/{}".format(self.remote_base, self.log_relative_path)])
            elif provider == 'oracle_bmc':
                tmp_command_directory = tempfile.mkdtemp()
                self.log_relative_path = self.log_relative_path.replace(':', '.')
                config = json.load(open('/root/config.json', "r+"))
                execute_cmd = '/usr/lib/hadoop2/bin/hadoop' + ' dfs' + ' -Dfs.oraclebmc.client.auth.tenantId={}'.format(
                    config['cloud_config']['storage_tenant_id'])
                execute_cmd += ' -Dfs.oraclebmc.client.auth.userId={}'.format(config['cloud_config']['compute_user_id'])
                execute_cmd += ' -Dfs.oraclebmc.client.auth.fingerprint={}'.format(
                    config['cloud_config']['storage_key_finger_print'])
                execute_cmd += ' -Dfs.oraclebmc.client.auth.pemfilecontent="{}"'.format(
                    config['cloud_config']['storage_api_private_rsa_key'])
                execute_cmd += " -copyFromLocal" + " -f" + " " + local_loc + " {}/{}".format(self.remote_base,
                                                                                             self.log_relative_path)
                command_file = open(tmp_command_directory + "/command.sh", "w+")
                command_file.write(execute_cmd)
                command_file.close()
                os.system("source {}/command.sh".format(tmp_command_directory))
            elif provider == "gcp":
                remote_loc = os.path.join(self.remote_base, self.log_relative_path.replace(':', '.'))
                execute_cmd = ["gsutil", "-m", "cp", "-R"]
                execute_cmd.extend([local_loc, remote_loc])
            else:
                execute_cmd = ['s3cmd', 'put', '--recursive', '-c', '/usr/lib/hustler/s3cfg']
                execute_cmd.extend([local_loc, remote_loc])

            if provider[:6] != "oracle":
                process = subprocess.Popen(execute_cmd, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)

        self.closed = True

    def _read(self, ti, try_number, metadata=None):
        """
        Read logs of given task instance and try_number from S3 remote storage.
        If failed, read the log from task instance host machine.
        :param ti: task instance object
        :param try_number: task instance try_number to read logs from
        """
        # Explicitly getting log relative path is necessary as the given
        # task instance might be different than task instance passed in
        # in set_context method.

        # fetch the logs first either from local file system or worker http endpoint
        log, condition_map = super(QDSTaskHandler, self)._read(ti, try_number, metadata)
        if not condition_map.get("error_while_fetch", True):
            return log, condition_map

        # fetch from remote storage if not avaialbe on local
        log_relative_path = self._render_filename(ti, try_number)
        remote_loc = os.path.join(self.remote_base, log_relative_path)
        tmp_file = tempfile.NamedTemporaryFile()
        provider = "kubernetes" if conf.getboolean("qubole", "K8S_RUNTIME") else os.environ.get('PROVIDER', "")

        if provider == "kubernetes":
            execute_cmd = ['aws', 's3', 'cp' ]
            execute_cmd.extend([remote_loc, tmp_file.name])
        elif provider == 'azure':
            # We have to do this because azure does not support colon in the file path
            log_relative_path = log_relative_path.replace(':', '.')
            execute_cmd = ['/usr/lib/hadoop2/bin/hadoop', 'dfs',
                           '-Dfs.azure.account.key.{}.blob.core.windows.net={}'.format(
                               os.environ.get("AZURE_STORAGE_ACCOUNT"), os.environ.get("AZURE_STORAGE_ACCESS_KEY"))]
            execute_cmd.extend(
                ["-copyToLocal", "-f", "{}/{}".format(conf.get("core", "remote_base_log_folder"), log_relative_path),
                 tmp_file.name])
        elif provider == 'oracle_bmc':
            tmp_command_directory = tempfile.mkdtemp()
            log_relative_path = log_relative_path.replace(':', '.')
            config = json.load(open('/root/config.json', "r+"))
            execute_cmd = '/usr/lib/hadoop2/bin/hadoop' + ' dfs' + ' -Dfs.oraclebmc.client.auth.tenantId={}'.format(
                config['cloud_config']['storage_tenant_id'])
            execute_cmd += ' -Dfs.oraclebmc.client.auth.userId={}'.format(config['cloud_config']['compute_user_id'])
            execute_cmd += ' -Dfs.oraclebmc.client.auth.fingerprint={}'.format(
                config['cloud_config']['storage_key_finger_print'])
            execute_cmd += ' -Dfs.oraclebmc.client.auth.pemfilecontent="{}"'.format(
                config['cloud_config']['storage_api_private_rsa_key'])
            execute_cmd += " -copyToLocal" + " -f" + " {}/{}".format(conf.get("core", "remote_base_log_folder"),
                                                                     log_relative_path) + " " + tmp_file.name
            command_file = open(tmp_command_directory + "/command.sh", "w+")
            command_file.write(execute_cmd)
            command_file.close()
            os.system("source {}/command.sh".format(tmp_command_directory))
        elif provider == 'gcp':
            remote_loc = os.path.join(self.remote_base, self.log_relative_path.replace(':', '.'))
            execute_cmd = ["gsutil", "-m", "cp", "-R"]
            execute_cmd.extend([remote_loc, tmp_file.name])
        else:
            execute_cmd = ['s3cmd', 'get', '-c', '/usr/lib/hustler/s3cfg']
            execute_cmd.extend([remote_loc, tmp_file.name, '--force'])

        if provider[:6] != "oracle":
            process = subprocess.Popen(execute_cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            process.wait()
        log += '*** Fetching log from Remote: {}\n'.format(remote_loc)
        log += ('*** Note: Remote logs are only available once '
                'tasks have completed.\n')
        try:
            with open(tmp_file.name) as f:
                log += "".join(f.readlines())
        except Exception as e:
            log = ''

        return log, {'end_of_log': True}

    @staticmethod
    def _get_provider() -> str:
        return conf.get('qubole', 'PROVIDER')
