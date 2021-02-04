from bs4 import BeautifulSoup # Need to install BeautifulSoup & lxml for these changes
import urllib2
import os
import pickle
from datetime import datetime
import requests
import json
import psutil
from send_email import notify
import configparser

# Config to connect monit remotely, will be needed later to show monit dashboard
# set httpd port 2812 and
# use address <instance-public-ip>
# allow 0.0.0.0/0.0.0.0

def convert_html_dict(html_data):
    soup = BeautifulSoup(html_data, "lxml")
    table = str(soup.body.center.table)
    table_data = [[cell.text for cell in row("td")]
                  for row in BeautifulSoup(table)("tr")]

    return dict(table_data)

def init_service_details():
    service_details = {}
    service_details['status'] = 'running'
    service_details['latest_heartbeat'] = datetime.now()
    service_details['alert_on_failure'] = False
    return service_details

def init_disk_usage_details():
    disk_usage_details = {}
    disk_usage_details['usage'] = 0
    disk_usage_details['alert_on_failure'] = False
    return disk_usage_details

print("<------------------->")
print("Starting health checks at: " + str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

# Overall logic:
# Fetch the status of each service from monit http end point
# Below is the overall logic to determine sending alerts, results of every health check run stored in a pickle file
# R -> Running, F -> Failed, RR means Running in previous(read from pickle file) and current health check
# RR > don't send mail, set mail on failure to 0
# RF / FF > if mail not sent & window crossed, send mail & set mail sent to 1
# FR > send mail, set mail on failure to 0

monit_data = {}
html_data = urllib2.urlopen("http://localhost:2812/scheduler").read()
scheduler_monit_data = convert_html_dict(html_data)
monit_data['scheduler'] = scheduler_monit_data

html_data = urllib2.urlopen("http://localhost:2812/webserver").read()
webserver_monit_data = convert_html_dict(html_data)
monit_data['webserver'] = webserver_monit_data

use_celery_airflow = os.getenv("USE_CELERY_AIRFLOW", "False")
if use_celery_airflow == "True":
    html_data = urllib2.urlopen("http://localhost:2812/worker").read()
    worker_monit_data = convert_html_dict(html_data)
    monit_data['worker'] = worker_monit_data

use_cluster_broker_airflow = os.getenv("USE_CELERY_AIRFLOW", "False")
if use_cluster_broker_airflow == "True":
    html_data = urllib2.urlopen("http://localhost:2812/rabbitmq").read()
    rabbitmq_monit_data = convert_html_dict(html_data)
    monit_data['rabbitmq'] = rabbitmq_monit_data

print("Health check data for all services")
print(monit_data)

airflow_home = os.getenv("AIRFLOW_HOME", "/usr/lib/airflow")
services_heartbeats_file_location = os.path.join(airflow_home, "services_heartbeats.pkl")
services_details = {}
with open( services_heartbeats_file_location, "rb" ) as f:
    try:
        services_details = pickle.load(f)
    except EOFError:
        pass

updated_services_details = {}
message = ""

current_healthcheck_time = datetime.now()
for key in monit_data.keys():
    if services_details is not None and services_details.has_key(key) and services_details[key] is not None:
        previous_run_service_details = services_details[key]
        current_run_service_details = previous_run_service_details.copy()

        monit_service_status = monit_data[key]['Status']
        if monit_service_status == "running":
            print("Service: " + key + " is up")
            if previous_run_service_details['status'] == "down" and previous_run_service_details['alert_on_failure'] == True:
                message += "Service: " + key + " is now up.\n"

            current_run_service_details = init_service_details()
        else:
            print("Service: " + key + " is not up")
            latest_heartbeat = previous_run_service_details['latest_heartbeat']
            time_lapsed_since_latest_heartbeat = current_healthcheck_time - latest_heartbeat
            if previous_run_service_details['alert_on_failure'] == False and time_lapsed_since_latest_heartbeat.seconds > 10*60:
                message += "Service: " + key + " is not up. Latest heartbeat reported: " + str(latest_heartbeat.strftime("%Y-%m-%d %H:%M:%S")) + "\n"
                current_run_service_details['alert_on_failure'] = True

            current_run_service_details['status'] = 'down'
            current_run_service_details['latest_heartbeat'] = latest_heartbeat

        updated_services_details[key] = current_run_service_details
    else:
        # To handle the scenario when the cron starts running for the first time.
        # Only populate the config, not checking the status as the cron might get triggered first and the services are
        # still coming up

        service_details = init_service_details()
        updated_services_details[key] = service_details

disk_usage_data = {}

services_logs_location = "/media/ephemeral0/logs/airflow/"
du = psutil.disk_usage(services_logs_location)
usage = du.percent
print("Services Logs usage: " + str(usage) + "%")
services_logs_usage = {}
disk_usage_data['services_logs_usage'] = services_logs_usage
services_logs_usage['usage'] = usage
services_logs_usage['location'] = services_logs_location

for key in disk_usage_data.keys():
    if services_details is not None and services_details.has_key(key) and services_details[key] is not None:
        du_disk_usage_details = disk_usage_data[key]
        usage = du_disk_usage_details['usage']
        previous_run_disk_usage_details = services_details[key]
        current_run_disk_usage_details = previous_run_disk_usage_details.copy()
        if usage > 90:
            if previous_run_disk_usage_details['alert_on_failure'] == False:
                message += "Disk usage is: " + str(usage) + "% on the mount having airflow logs at: " + du_disk_usage_details['location']
                current_run_disk_usage_details['alert_on_failure'] = True
            current_run_disk_usage_details['usage'] = usage
        else:
            if previous_run_disk_usage_details['alert_on_failure'] == True:
                message += "Disk usage is now fine at: " + str(usage) + "% on the mount having airflow logs at: " + du_disk_usage_details['location']
                current_run_disk_usage_details['alert_on_failure'] = False
            current_run_disk_usage_details['usage'] = usage

        updated_services_details[key] = current_run_disk_usage_details
    else:
        disk_usage_details = init_disk_usage_details()
        updated_services_details[key] = disk_usage_details

with open(services_heartbeats_file_location, "wb") as f:
    pickle.dump(updated_services_details, f)

if message != "":
    print("Sending alert..")
    print(message)
    notify(message, "airflow-cluster-alerts@qubole.com")
    config = configparser.ConfigParser()
    config.read("{}/airflow.cfg".format(os.getenv("AIRFLOW_HOME", "/usr/lib/airflow")))
    if config.get('core', 'alert_via_email'):
        if config.get('core', 'alert_emails') != "":
            emails = config.get('core', 'alert_emails')
            print("Sending alert to {}".format(emails))
            notify(message, emails)
