#We had to write this module in python because parsing a json file in bash is very cumbersome
import json
import os

config = json.load(open('/root/config.json', "r+"))
f= open("/etc/profile.d/airflow.sh","a+")
if os.environ.get("PROVIDER") == "azure":
    f.write("export AZURE_STORAGE_ACCOUNT=%s\n" % (config['cloud_config']['storage_account_name']))
    f.write("export AZURE_STORAGE_ACCESS_KEY=%s\n" % (config['cloud_config']['storage_account_key']))
f.close()
