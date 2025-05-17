#!/usr/bin/env python3
"""
Scheduler for triggering Celery tasks using APScheduler.
This script schedules the download_images_from_drive_folder_async task to run periodically.
It reads listing information from Google Sheets to find Drive folders that need image downloads.
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ProcessPoolExecutor
import logging
import os
import sys
import re
import json
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/image_scheduler.log')
    ]
)
logger = logging.getLogger('image_scheduler')

# Import the Celery task
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from celery_worker import download_images_from_drive_folder_async

# Configuration
# IMAGE_CACHE_DIR = "static/images"
IMAGE_CACHE_DIR = "/home/settleradmin/production/Website/static/images"
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

# Regular expression to extract folder ID from Google Drive links
folder_id_pattern = re.compile(r"https://drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)(?:\?.*)?")

# Google API setup
scope = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]


def get_credentials_path():
    """Get the path to Google API credentials file."""
    try:
        with open('config.json') as config_file:
            config = json.load(config_file)
            # First try environment variable, then config file
            creds_path = os.getenv('GOOGLE_CLOUD_CREDENTIALS') or config.get('creds_path')
            if not creds_path:
                # Hardcoded paths as fallback (same as in your backend_sandbox.py)
                creds_path = os.path.expanduser("/home/settleradmin/production/Website/creds.json")
                if not os.path.exists(creds_path):
                    alternatives = [
                        "/home/settleradmin/production/Website/creds.json"
                    ]
                    for path in alternatives:
                        if os.path.exists(os.path.expanduser(path)):
                            creds_path = os.path.expanduser(path)
                            break
    except (FileNotFoundError, json.JSONDecodeError):
        # If config.json doesn't exist or is invalid, use hardcoded path
        creds_path = os.path.expanduser("/home/settleradmin/production/Website/creds.json")

    if not os.path.exists(creds_path):
        logger.error(f"Credentials file not found at {creds_path}")

    return creds_path


def initialize_sheets():
    """Initialize Google Sheets API and return worksheet."""
    creds_path = get_credentials_path()
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        client = gspread.authorize(creds)
        worksheet = client.open("Owners - December backup").worksheet("owner listings")
        return worksheet
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
        return None


def normalize_folder_link(folder_link):
    """Extract folder ID from Google Drive link."""
    if not folder_link:
        return None

    folder_match = folder_id_pattern.search(folder_link)
    if folder_match:
        return folder_match.group(1)
    return None


def get_folders_to_process():
    """Get folder IDs and names from Google Sheets."""
    worksheet = initialize_sheets()
    if not worksheet:
        logger.error("Failed to get worksheet")
        return []

    folders = []
    try:
        rows = worksheet.get_all_values()
        # Skip header row if present
        if rows and rows[0][0] == "ID" or rows[0][0].strip().lower() == "id":
            rows = rows[1:]

        id_col = 0  # Column A for listing ID
        drive_link_col = 16  # Column Q for Google Drive folder links

        for row in rows:
            if len(row) <= drive_link_col:
                continue

            listing_id = row[id_col].strip() if id_col < len(row) else None
            if not listing_id or not re.match(r'^\d{6}$', listing_id):  # Fixed regex pattern
                continue  # Skip rows without valid IDs

            folder_link = row[drive_link_col]
            if not folder_link:
                continue  # Skip listings without Drive links

            folder_id = normalize_folder_link(folder_link)
            if not folder_id:
                continue  # Skip listings with invalid Drive links

            # Create folder name in the same format as your Flask app
            folder_name = f"{listing_id}_დამუშავებული"

            # Check if images already exist locally
            full_folder_path = os.path.join(IMAGE_CACHE_DIR, folder_name)
            if not os.path.exists(full_folder_path):
                folders.append({
                    "id": folder_id,
                    "name": folder_name,
                    "listing_id": listing_id
                })

        logger.info(f"Found {len(folders)} folders that need to be processed")
        return folders

    except Exception as e:
        logger.error(f"Error getting folders from Google Sheets: {e}")
        return []


def trigger_downloads():
    """Trigger download task for folders from Google Sheets."""
    logger.info("Starting scheduled image download job")

    folders = get_folders_to_process()
    if not folders:
        logger.info("No folders need processing at this time")
        return

    # Trigger a Celery task for each folder
    for folder in folders:
        folder_id = folder.get("id")
        folder_name = folder.get("name")
        listing_id = folder.get("listing_id")

        logger.info(f"Scheduling download for listing {listing_id}: {folder_name} ({folder_id})")
        try:
            # Schedule the task with Celery
            task = download_images_from_drive_folder_async.delay(folder_id, folder_name)
            logger.info(f"Task scheduled with id: {task.id}")
        except Exception as e:
            logger.error(f"Failed to schedule task for folder {folder_name}: {e}")


def main():
    """Main function to set up and start the scheduler."""
    logger.info("Starting image download scheduler")

    # Define executors
    executors = {
        'default': {'type': 'threadpool', 'max_workers': 10},
        'processpool': ProcessPoolExecutor(max_workers=3)
    }

    # Create scheduler
    scheduler = BlockingScheduler(executors=executors)

    # Schedule the job - run every 30 minutes to check for new Drive folders
    scheduler.add_job(
        trigger_downloads,
        'interval',
        minutes=30,  # Run more frequently to catch new listings
        id='image_download_job',
        replace_existing=True,
        next_run_time=datetime.now()  # Run immediately on startup
    )

    logger.info("Scheduler configured, starting now...")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
