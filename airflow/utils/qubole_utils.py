from flask_appbuilder.urltools import Stack
import os
import functools

from flask import flash, redirect, url_for, make_response, jsonify
from flask_appbuilder._compat import as_unicode
from flask_appbuilder.const import LOGMSG_ERR_SEC_ACCESS_DENIED, FLAMSG_ERR_SEC_ACCESS_DENIED, PERMISSION_PREFIX


airflow_webserver_proxy_uri = os.getenv('AIRFLOW_WEBSERVER_PROXY_URI', "")

def proxified_get_redirect(self):
    from flask import session
    index_url = self.appbuilder.get_url_for_index
    page_history = Stack(session.get('page_history', []))
    if page_history.pop() is None:
        return index_url
    session['page_history'] = page_history.to_json()
    url = page_history.pop() or index_url
    return clean_url(url)


@property
def proxified_get_url_for_index(self):
    return "/{}/home".format(airflow_webserver_proxy_uri)

@property
def proxified_get_url_for_login(self):
    return "/{}/login/".format(airflow_webserver_proxy_uri)

def proxified_get_home():
    return "/{}/home".format(airflow_webserver_proxy_uri)

def has_access(f):

    if hasattr(f, '_permission_name'):
        permission_str = f._permission_name
    else:
        permission_str = f.__name__

    def wraps(self, *args, **kwargs):
        permission_str = PERMISSION_PREFIX + f._permission_name
        if self.appbuilder.sm.has_access(permission_str, self.__class__.__name__):
            return f(self, *args, **kwargs)
        else:
            flash(as_unicode(FLAMSG_ERR_SEC_ACCESS_DENIED), "danger")
        return redirect("/{}/home".format(airflow_webserver_proxy_uri))
    f._permission_name = permission_str
    return functools.update_wrapper(wraps, f)

def clean_url(url, params = False):
    if url is None:
        return None
    if "http" in url:
        return url
    try:
        from urlparse import urlparse
    except:
        from urllib.parse import urlparse
    if "airflow-rbacwebserver" in url:
        return url
    else:
        path = urlparse(url).path
        url = "/{}{}".format(airflow_webserver_proxy_uri, path)
        return url

def override_route_base(module):
    from importlib import import_module
    prepend_url = "/"+airflow_webserver_proxy_uri


    airflow_views = ["AirflowBaseView", "SlaMissModelView", "XComModelView", "ConnectionModelView", "PoolModelView", "VariableModelView", "JobModelView",
                     "DagRunModelView", "LogModelView", "TaskInstanceModelView", "DagModelView"]
    appbuilder_security_views = ["PermissionModelView", "ViewMenuModelView", "PermissionViewModelView", "ResetMyPasswordView",
                                 "ResetPasswordView", "UserModelView", "RoleModelView", "RegisterUserModelView", "AuthView"]

    if module == "airflow":
        for v in airflow_views:
            view = getattr(import_module("airflow.www.views"), v)
            if not "/airflow-rbacwebserver-" in view.route_base:
                view.route_base = prepend_url+view.route_base

        # from airflow.utils.prometheus_exporter import RBACMetrics
        # RBACMetrics.route_base = prepend_url+RBACMetrics.route_base

    if module == "appbuilder":
        from flask_appbuilder.baseviews import BaseView
        BaseView.route_base = prepend_url
        from flask_appbuilder.views import UtilView
        UtilView.route_base = prepend_url

        for v in appbuilder_security_views:
            view = getattr(import_module("flask_appbuilder.security.views"), v)
            if not "/airflow-rbacwebserver-" in view.route_base:
                view.route_base = prepend_url+view.route_base

