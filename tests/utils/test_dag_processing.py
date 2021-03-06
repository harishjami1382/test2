#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from airflow.configuration import conf
from airflow.jobs.local_task_job import LocalTaskJob as LJ
from airflow.jobs.scheduler_job import DagFileProcessorProcess
from airflow.models import DagBag, TaskInstance as TI
from airflow.models.taskinstance import SimpleTaskInstance
from airflow.utils import timezone
from airflow.utils.dag_processing import (
    DagFileProcessorAgent, DagFileProcessorManager, DagFileStat, FailureCallbackRequest,
)
from airflow.utils.file import correct_maybe_zipped
from airflow.utils.session import create_session
from airflow.utils.state import State
from tests.test_utils.config import conf_vars
from tests.test_utils.db import clear_db_runs

TEST_DAG_FOLDER = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), os.pardir, 'dags')

DEFAULT_DATE = timezone.datetime(2016, 1, 1)

SETTINGS_FILE_VALID = """
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'airflow.task': {
            'format': '[%(asctime)s] {%(process)d %(filename)s:%(lineno)d} %(levelname)s - %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'airflow.task',
            'stream': 'ext://sys.stdout'
        },
        'task': {
            'class': 'logging.StreamHandler',
            'formatter': 'airflow.task',
            'stream': 'ext://sys.stdout'
        },
    },
    'loggers': {
        'airflow': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False
        },
        'airflow.task': {
            'handlers': ['task'],
            'level': 'INFO',
            'propagate': False,
        },
    }
}
"""

SETTINGS_DEFAULT_NAME = 'custom_airflow_local_settings'


class settings_context:  # pylint: disable=invalid-name
    """
    Sets a settings file and puts it in the Python classpath

    :param content:
          The content of the settings file
    """

    def __init__(self, content, directory=None, name='LOGGING_CONFIG'):
        self.content = content
        self.settings_root = tempfile.mkdtemp()
        filename = "{}.py".format(SETTINGS_DEFAULT_NAME)

        if directory:
            # Replace slashes by dots
            self.module = directory.replace('/', '.') + '.' + SETTINGS_DEFAULT_NAME + '.' + name

            # Create the directory structure
            dir_path = os.path.join(self.settings_root, directory)
            pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)

            # Add the __init__ for the directories
            # This is required for Python 2.7
            basedir = self.settings_root
            for part in directory.split('/'):
                open(os.path.join(basedir, '__init__.py'), 'w').close()
                basedir = os.path.join(basedir, part)
            open(os.path.join(basedir, '__init__.py'), 'w').close()

            self.settings_file = os.path.join(dir_path, filename)
        else:
            self.module = SETTINGS_DEFAULT_NAME + '.' + name
            self.settings_file = os.path.join(self.settings_root, filename)

    def __enter__(self):
        with open(self.settings_file, 'w') as handle:
            handle.writelines(self.content)
        sys.path.append(self.settings_root)
        conf.set(
            'logging',
            'logging_config_class',
            self.module
        )
        return self.settings_file

    def __exit__(self, *exc_info):
        # shutil.rmtree(self.settings_root)
        # Reset config
        conf.set('logging', 'logging_config_class', '')
        sys.path.remove(self.settings_root)


class TestDagFileProcessorManager(unittest.TestCase):
    def setUp(self):
        clear_db_runs()

    def test_set_file_paths_when_processor_file_path_not_in_new_file_paths(self):
        manager = DagFileProcessorManager(
            dag_directory='directory',
            max_runs=1,
            processor_factory=MagicMock().return_value,
            processor_timeout=timedelta.max,
            signal_conn=MagicMock(),
            async_mode=True)

        mock_processor = MagicMock()
        mock_processor.stop.side_effect = AttributeError(
            'DagFileProcessor object has no attribute stop')
        mock_processor.terminate.side_effect = None

        manager._processors['missing_file.txt'] = mock_processor
        manager._file_stats['missing_file.txt'] = DagFileStat(0, 0, None, None, 0)

        manager.set_file_paths(['abc.txt'])
        self.assertDictEqual(manager._processors, {})

    def test_set_file_paths_when_processor_file_path_is_in_new_file_paths(self):
        manager = DagFileProcessorManager(
            dag_directory='directory',
            max_runs=1,
            processor_factory=MagicMock().return_value,
            processor_timeout=timedelta.max,
            signal_conn=MagicMock(),
            async_mode=True)

        mock_processor = MagicMock()
        mock_processor.stop.side_effect = AttributeError(
            'DagFileProcessor object has no attribute stop')
        mock_processor.terminate.side_effect = None

        manager._processors['abc.txt'] = mock_processor

        manager.set_file_paths(['abc.txt'])
        self.assertDictEqual(manager._processors, {'abc.txt': mock_processor})

    def test_find_zombies(self):
        manager = DagFileProcessorManager(
            dag_directory='directory',
            max_runs=1,
            processor_factory=MagicMock().return_value,
            processor_timeout=timedelta.max,
            signal_conn=MagicMock(),
            async_mode=True)

        dagbag = DagBag(TEST_DAG_FOLDER)
        with create_session() as session:
            session.query(LJ).delete()
            dag = dagbag.get_dag('example_branch_operator')
            dag.sync_to_db()
            task = dag.get_task(task_id='run_this_first')

            ti = TI(task, DEFAULT_DATE, State.RUNNING)
            local_job = LJ(ti)
            local_job.state = State.SHUTDOWN
            local_job.id = 1
            ti.job_id = local_job.id

            session.add(local_job)
            session.add(ti)
            session.commit()

            manager._last_zombie_query_time = timezone.utcnow() - timedelta(
                seconds=manager._zombie_threshold_secs + 1)
            manager._find_zombies()  # pylint: disable=no-value-for-parameter
            requests = manager._callback_to_execute[dag.full_filepath]
            self.assertEqual(1, len(requests))
            self.assertEqual(requests[0].full_filepath, dag.full_filepath)
            self.assertEqual(requests[0].msg, "Detected as zombie")
            self.assertIsInstance(requests[0].simple_task_instance, SimpleTaskInstance)
            self.assertEqual(ti.dag_id, requests[0].simple_task_instance.dag_id)
            self.assertEqual(ti.task_id, requests[0].simple_task_instance.task_id)
            self.assertEqual(ti.execution_date, requests[0].simple_task_instance.execution_date)

            session.query(TI).delete()
            session.query(LJ).delete()

    def test_handle_failure_callback_with_zobmies_are_correctly_passed_to_dag_file_processor(self):
        """
        Check that the same set of failure callback with zombies are passed to the dag
        file processors until the next zombie detection logic is invoked.
        """
        test_dag_path = os.path.join(TEST_DAG_FOLDER, 'test_example_bash_operator.py')
        with conf_vars({('scheduler', 'max_threads'): '1',
                        ('core', 'load_examples'): 'False'}):
            dagbag = DagBag(test_dag_path)
            with create_session() as session:
                session.query(LJ).delete()
                dag = dagbag.get_dag('test_example_bash_operator')
                dag.sync_to_db()
                task = dag.get_task(task_id='run_this_last')

                ti = TI(task, DEFAULT_DATE, State.RUNNING)
                local_job = LJ(ti)
                local_job.state = State.SHUTDOWN
                local_job.id = 1
                ti.job_id = local_job.id

                session.add(local_job)
                session.add(ti)
                session.commit()
                fake_failure_callback_requests = [
                    FailureCallbackRequest(
                        full_filepath=dag.full_filepath,
                        simple_task_instance=SimpleTaskInstance(ti),
                        msg="Message"
                    )
                ]

            class FakeDagFileProcessorRunner(DagFileProcessorProcess):
                # This fake processor will return the zombies it received in constructor
                # as its processing result w/o actually parsing anything.
                def __init__(self, file_path, pickle_dags, dag_id_white_list, failure_callback_requests):
                    super().__init__(file_path, pickle_dags, dag_id_white_list, failure_callback_requests)
                    self._result = failure_callback_requests, 0

                def start(self):
                    pass

                @property
                def start_time(self):
                    return DEFAULT_DATE

                @property
                def pid(self):
                    return 1234

                @property
                def done(self):
                    return True

                @property
                def result(self):
                    return self._result

            def processor_factory(file_path, failure_callback_requests):
                return FakeDagFileProcessorRunner(
                    file_path,
                    False,
                    [],
                    failure_callback_requests
                )

            async_mode = 'sqlite' not in conf.get('core', 'sql_alchemy_conn')
            processor_agent = DagFileProcessorAgent(test_dag_path,
                                                    1,
                                                    processor_factory,
                                                    timedelta.max,
                                                    async_mode)
            processor_agent.start()
            parsing_result = []
            if not async_mode:
                processor_agent.heartbeat()
            while not processor_agent.done:
                if not async_mode:
                    processor_agent.wait_until_finished()
                parsing_result.extend(processor_agent.harvest_simple_dags())

            self.assertEqual(len(fake_failure_callback_requests), len(parsing_result))
            self.assertEqual(
                set(zombie.simple_task_instance.key for zombie in fake_failure_callback_requests),
                set(result.simple_task_instance.key for result in parsing_result)
            )

    @mock.patch("airflow.jobs.scheduler_job.DagFileProcessorProcess.pid", new_callable=PropertyMock)
    @mock.patch("airflow.jobs.scheduler_job.DagFileProcessorProcess.kill")
    def test_kill_timed_out_processors_kill(self, mock_kill, mock_pid):
        mock_pid.return_value = 1234
        manager = DagFileProcessorManager(
            dag_directory='directory',
            max_runs=1,
            processor_factory=MagicMock().return_value,
            processor_timeout=timedelta(seconds=5),
            signal_conn=MagicMock(),
            async_mode=True)

        processor = DagFileProcessorProcess('abc.txt', False, [], [])
        processor._start_time = timezone.make_aware(datetime.min)
        manager._processors = {'abc.txt': processor}
        manager._kill_timed_out_processors()
        mock_kill.assert_called_once_with()

    @mock.patch("airflow.jobs.scheduler_job.DagFileProcessorProcess.pid", new_callable=PropertyMock)
    @mock.patch("airflow.jobs.scheduler_job.DagFileProcessorProcess")
    def test_kill_timed_out_processors_no_kill(self, mock_dag_file_processor, mock_pid):
        mock_pid.return_value = 1234
        manager = DagFileProcessorManager(
            dag_directory='directory',
            max_runs=1,
            processor_factory=MagicMock().return_value,
            processor_timeout=timedelta(seconds=5),
            signal_conn=MagicMock(),
            async_mode=True)

        processor = DagFileProcessorProcess('abc.txt', False, [], [])
        processor._start_time = timezone.make_aware(datetime.max)
        manager._processors = {'abc.txt': processor}
        manager._kill_timed_out_processors()
        mock_dag_file_processor.kill.assert_not_called()


class TestDagFileProcessorAgent(unittest.TestCase):
    def setUp(self):
        # Make sure that the configure_logging is not cached
        self.old_modules = dict(sys.modules)

    def tearDown(self):
        # Remove any new modules imported during the test run. This lets us
        # import the same source files for more than one test.
        for mod in sys.modules:
            if mod not in self.old_modules:
                del sys.modules[mod]

    def test_reload_module(self):
        """
        Configure the context to have logging.logging_config_class set to a fake logging
        class path, thus when reloading logging module the airflow.processor_manager
        logger should not be configured.
        """
        with settings_context(SETTINGS_FILE_VALID):
            # Launch a process through DagFileProcessorAgent, which will try
            # reload the logging module.
            def processor_factory(file_path, zombies):
                return DagFileProcessorProcess(file_path,
                                               False,
                                               [],
                                               zombies)

            test_dag_path = os.path.join(TEST_DAG_FOLDER, 'test_scheduler_dags.py')
            async_mode = 'sqlite' not in conf.get('core', 'sql_alchemy_conn')

            log_file_loc = conf.get('logging', 'DAG_PROCESSOR_MANAGER_LOG_LOCATION')
            try:
                os.remove(log_file_loc)
            except OSError:
                pass

            # Starting dag processing with 0 max_runs to avoid redundant operations.
            processor_agent = DagFileProcessorAgent(test_dag_path,
                                                    0,
                                                    processor_factory,
                                                    timedelta.max,
                                                    async_mode)
            processor_agent.start()
            if not async_mode:
                processor_agent.heartbeat()

            processor_agent._process.join()

            # Since we are reloading logging config not creating this file,
            # we should expect it to be nonexistent.
            self.assertFalse(os.path.isfile(log_file_loc))

    # TODO: Fix Testcase leading to infinite loop
    # def test_parse_once(self):
    #     def processor_factory(file_path, zombies):
    #         return DagFileProcessorProcess(file_path,
    #                                        False,
    #                                        [],
    #                                        zombies)
    #
    #     test_dag_path = os.path.join(TEST_DAG_FOLDER, 'test_scheduler_dags.py')
    #     async_mode = 'sqlite' not in conf.get('core', 'sql_alchemy_conn')
    #     processor_agent = DagFileProcessorAgent(test_dag_path,
    #                                             1,
    #                                             processor_factory,
    #                                             timedelta.max,
    #                                             async_mode)
    #     processor_agent.start()
    #     parsing_result = []
    #     if not async_mode:
    #         processor_agent.heartbeat()
    #     while not processor_agent.done:
    #         if not async_mode:
    #             processor_agent.wait_until_finished()
    #         parsing_result.extend(processor_agent.harvest_simple_dags())
    #
    #     dag_ids = [result.dag_id for result in parsing_result]
    #     self.assertEqual(dag_ids.count('test_start_date_scheduling'), 1)

    def test_launch_process(self):
        def processor_factory(file_path, zombies):
            return DagFileProcessorProcess(file_path,
                                           False,
                                           [],
                                           zombies)

        test_dag_path = os.path.join(TEST_DAG_FOLDER, 'test_scheduler_dags.py')
        async_mode = 'sqlite' not in conf.get('core', 'sql_alchemy_conn')

        log_file_loc = conf.get('logging', 'DAG_PROCESSOR_MANAGER_LOG_LOCATION')
        try:
            os.remove(log_file_loc)
        except OSError:
            pass

        # Starting dag processing with 0 max_runs to avoid redundant operations.
        processor_agent = DagFileProcessorAgent(test_dag_path,
                                                0,
                                                processor_factory,
                                                timedelta.max,
                                                async_mode)
        processor_agent.start()
        if not async_mode:
            processor_agent.heartbeat()

        processor_agent._process.join()

        self.assertTrue(os.path.isfile(log_file_loc))


class TestCorrectMaybeZipped(unittest.TestCase):
    @mock.patch("zipfile.is_zipfile")
    def test_correct_maybe_zipped_normal_file(self, mocked_is_zipfile):
        path = '/path/to/some/file.txt'
        mocked_is_zipfile.return_value = False

        dag_folder = correct_maybe_zipped(path)

        self.assertEqual(dag_folder, path)

    @mock.patch("zipfile.is_zipfile")
    def test_correct_maybe_zipped_normal_file_with_zip_in_name(self, mocked_is_zipfile):
        path = '/path/to/fakearchive.zip.other/file.txt'
        mocked_is_zipfile.return_value = False

        dag_folder = correct_maybe_zipped(path)

        self.assertEqual(dag_folder, path)

    @mock.patch("zipfile.is_zipfile")
    def test_correct_maybe_zipped_archive(self, mocked_is_zipfile):
        path = '/path/to/archive.zip/deep/path/to/file.txt'
        mocked_is_zipfile.return_value = True

        dag_folder = correct_maybe_zipped(path)

        assert mocked_is_zipfile.call_count == 1
        (args, kwargs) = mocked_is_zipfile.call_args_list[0]
        self.assertEqual('/path/to/archive.zip', args[0])

        self.assertEqual(dag_folder, '/path/to/archive.zip')
