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

import json
import os
import six
from flask import url_for
from typing import Dict

from flask import url_for

manifest = dict()  # type: Dict[str, str]


def configure_manifest_files(app):
    """
    Loads the manifest file and register the `url_for_asset_` template tag.

    :param app:
    :return:
    """

    def parse_manifest_json():
        # noinspection PyBroadException
        try:
            global manifest
            manifest_file = os.path.join(os.path.dirname(__file__),
                                         'static/dist/manifest.json')
            with open(manifest_file, 'r') as file:
                manifest.update(json.load(file))

                for k in manifest.keys():
                    manifest[k] = os.path.join("dist", manifest[k])
        except Exception:
            print("Please make sure to build the frontend in static/ directory and restart the server")

    def get_asset_url(filename):
        cdn_url = 'https://d3chibfrmv0usk.cloudfront.net/airflow/v1.10.9'
        if app.debug:
            parse_manifest_json()
        return '{}/static/{}'.format(cdn_url, manifest.get(filename, ''))

    parse_manifest_json()

    def get_url_for_asset():  # pylint: disable=unused-variable
        """
        Template tag to return the asset URL.
        WebPack renders the assets after minification and modification
        under the static/dist folder.
        This template tag reads the asset name in manifest.json and returns
        the appropriate file.
        """
        return dict(url_for_asset=get_asset_url)

    @app.context_processor
    def override_url_for():
        return dict(url_for=proxified_url_for, url_for_asset=get_asset_url)

    def proxified_url_for(endpoint, *args, **kwargs):
        cluster_id = os.getenv('CLUSTER_ID', "")
        cdn_url = 'https://d3chibfrmv0usk.cloudfront.net/airflow/v1.10.9'

        airflow_webserver_proxy_uri = "airflow-rbacwebserver-{0}".format(cluster_id)
        #airflow_webserver_proxy_admin_uri = "/{0}/home".format(airflow_webserver_proxy_uri)

        if not isinstance(endpoint, six.string_types):
            endpoint = args[0]

        if 'filename' in kwargs:
            return "{0}{1}".format(cdn_url, url_for(endpoint, **kwargs))
        if not url_for(endpoint, **kwargs).startswith("/airflow-rbacwebserver"):
            return "/{0}{1}".format(airflow_webserver_proxy_uri, url_for(endpoint, **kwargs))

        return url_for(endpoint, **kwargs)
