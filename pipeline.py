#to get the jobs data and store into the local machine .xlsx file

import os
import requests
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("Token")
PROJECT_ID = os.getenv("Project_ID")
# print("Project ID", PROJECT_ID)
BRANCH = os.getenv("Branch")
JOB_NAME = os.getenv("Job_Name")
git_url = os.getenv("GIT_URL")
url = f"{git_url}/api/v4/projects/{PROJECT_ID}/jobs/artifacts/{BRANCH}/raw/pipeline_jobs_report.xlsx?job={JOB_NAME}"
headers = {"PRIVATE-TOKEN": TOKEN}
r = requests.get(url, headers=headers, stream=True)

if r.status_code == 200:
   with open("pipeline_jobs_report.xlsx", "wb") as f:
      f.write(r.content)
   print("pipeline_jobs_report.xlsx downloaded successfully")
else:
   print("Error:", r.status_code)
   
# r.raise_for_status()
# with open("pipeline_jobs_report.xlsx", "wb") as f:
#    f.write(r.content)
# print("pipeline_jobs_report.xlsx downloaded successfully")
