import MySQLdb
import datetime
import sys
from qubole_assembly.send_email import notify
import configparser
import os

if len(sys.argv) < 2:
    print("Insufficient arguments. Bailing out")
    sys.exit(1)

def parse_connection_string(connection_string):
    connection_string_without_protocol = connection_string.split("//")[1]
    user = connection_string_without_protocol.split(":")[0]
    password = connection_string_without_protocol.split("@")[0].split(":")[1]
    host_with_port = connection_string_without_protocol.split("@")[1].split("/")[0]
    host = host_with_port.split(":")[0]
    port = int(host_with_port.split(":")[1]) if len(host_with_port.split(":")) > 1 else 3306
    database = connection_string_without_protocol.split("@")[1].split("/")[1]
    return host, port, user, password, database

is_active = True

try:
    connection_string = sys.argv[1]
    host, port, user, password, database = parse_connection_string(connection_string)
    db = MySQLdb.connect(host=host, port=port, user=user, passwd=password, db=database)
    cur = db.cursor()
    cur.execute("select MAX(start_date) from dag_run as t1 join (select * from dag where not fileloc like '%virtualenv/python27%') as t2 on t1.dag_id=t2.dag_id ")
    db_data = cur.fetchall()
    last_run_date = db_data[0][0]
    db.close()
    is_active = last_run_date > datetime.datetime.now() - datetime.timedelta(7)
except:
    is_active = False

if(not is_active):
    message = "Update: Cluster has been idle for some time now. Please terminate it if not in use"
    notify(message, "airflow-cluster-alerts@qubole.com")
    config = configparser.ConfigParser()
    config.read("{}/airflow.cfg".format(os.getenv("AIRFLOW_HOME", "/usr/lib/airflow")))
    if config.get('core', 'alert_via_email'):
        if config.get('core', 'alert_emails') != "":
            emails = config.get('core', 'alert_emails')
            print("Sending alert to {}".format(emails))
            notify(message, emails)
    print("Airflow cluster is idle.")
