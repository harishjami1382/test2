import os
import json
import requests
def notify(message, emails="airflow-cluster-alerts@qubole.com"):
    qubole_base_url = os.getenv("QUBOLE_BASE_URL", "https://api.qubole.com")
    qubole_cluster_api_token = os.getenv("QUBOLE_CLUSTER_API_TOKEN", "")
    url = qubole_base_url + '/opsapi/v1/cluster/notify_service_failure'

    payload = {
        "message": message,
        "email": emails
    }
    # Adding empty header as parameters are being sent in payload
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-AUTH-TOKEN": qubole_cluster_api_token
    }

    r = requests.put(url, data=json.dumps(payload), headers=headers)
    print(r.content)
