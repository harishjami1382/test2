import os
import requests


def get_sync_location():
    qubole_base_url = os.getenv("QUBOLE_BASE_URL", "https://api.qubole.com")
    qubole_cluster_api_token = os.getenv("QUBOLE_CLUSTER_API_TOKEN", "")
    url = qubole_base_url + '/opsapi/v1/clusters/airflow_sync_location.json'

    # Adding empty header as parameters are being sent in payload
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-AUTH-TOKEN": qubole_cluster_api_token
    }

    response = requests.get(url,  headers=headers)
    print("Response from get sync location API: {status_code} {content}".format(status_code=response.status_code,
                                                                                content=response.content))
    return response.json().get("location"), response.json().get("deployment_type")

def update_sync_location_variable():
    new_sync_location, sync_type = get_sync_location()
    if new_sync_location:
        sync_location_update_command = "sudo -i 's/SYNC_LOCATION=.*/SYNC_LOCATION={}/' " \
                                       "/etc/profile.d/airflow.sh".format(new_sync_location.replace("/", "\/"))
        os.system(sync_location_update_command)
        print("Ran command: {}, Successful!".format(sync_location_update_command))

    if sync_type:
        sync_location_update_command = "sudo sed -i 's/SYNC_TYPE=.*/SYNC_TYPE={}/' " \
                                        "/etc/profile.d/airflow.sh".format(sync_type)
        os.system(sync_location_update_command)
        print("Ran command: {}, Successful!".format(sync_location_update_command))

if __name__ == "__main__":
    update_sync_location_variable()
