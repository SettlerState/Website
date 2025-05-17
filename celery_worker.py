from celery import Celery
import logging
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials
import os
from utils import download_images_from_drive_folder

# Initialize Celery
app = Celery('tasks', broker='redis://localhost:6379/0')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Google Drive API
scope = ['https://www.googleapis.com/auth/drive']

#creds_path = r'/mnt/c/Users/Lenovo/PycharmProjects/Website/creds.json'
creds_path = os.path.expanduser("/home/settleradmin/production/Website/creds.json")
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
drive_service = build('drive', 'v3', credentials=creds)


@app.task
def download_images_from_drive_folder_async(folder_id, folder_name):
    """Background task to download images from Google Drive."""
    try:
        logger.info(f"Starting task: Downloading images for folder {folder_name} ({folder_id})")

        # Call the function from backend_sandbox
        image_paths = download_images_from_drive_folder(folder_id, folder_name)

        logger.info(f"Task completed: Downloaded {len(image_paths)} images for folder {folder_name} ({folder_id})")
        return image_paths
    except Exception as e:
        logger.error(f"Task failed: {e}")
        return str(e)
