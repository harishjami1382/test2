from airflow.www.security import AirflowSecurityManager
from flask_appbuilder.security.views import AuthDBView
from flask_login import login_user
from flask import request, g, redirect, flash
from flask_appbuilder.views import expose
from airflow import models
from airflow.settings import Session
from sqlalchemy.orm import scoped_session, sessionmaker
from flask_appbuilder.security.sqla.models import Role, User

class QuboleSecurityManager(AirflowSecurityManager):

    def __init__(self, appbuilder):
        super(AirflowSecurityManager, self).__init__(appbuilder)
        self.lm.request_loader(load_user_from_request)

class DefaultUser(object):
    def __init__(self, user):
        self.role = user['role']
        self.user_id = user['id']
        self.user_username = user['username']
        self.user_email = user['email']
        self.user_superuser = user['superuser']

    @property
    def is_active(self):
        '''Required by flask_login'''
        return True

    @property
    def is_authenticated(self):
        '''Required by flask_login'''
        return True

    @property
    def is_anonymous(self):
        '''Required by flask_login'''
        return False

    @property
    def data_profiling(self):
        '''Provides access to data profiling tools'''
        return True

    @property
    def is_superuser(self):
        '''Access all the things'''
        return self.user_superuser

    @property
    def get_id(self):
        return str(self.user_id)

    @property
    def username(self):
        return self.user_username

    @property
    def roles(self):
        return Session.query(Role).filter_by(name=self.role)

    def get_full_name(self):
        return str(self.user_email)

    @property
    def id(self):
        return None

def load_user_from_request(request):
    existing_user = Session.query(User).filter_by(email=request.headers['qboluseremail']).first()

    if existing_user is None:
        user = dict()
        user['id'] = request.headers['qboluserid']
        user['username'] = request.headers['qboluseremail']
        user['email'] = request.headers['qboluseremail']
        user['superuser'] = request.headers['clusteradmin'] == "true"
        user['is_authenticated'] = True
        user['role'] = request.headers['qbolairflowrole']
        return DefaultUser(user)
    login_user(existing_user, remember=False)
    return existing_user

