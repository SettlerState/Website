import os
import logging
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Google Drive API
scope = ['https://www.googleapis.com/auth/drive']

#creds_path = r'/mnt/c/Users/Lenovo/PycharmProjects/Website/creds.json'
creds_path = os.path.expanduser("/home/settleradmin/production/Website/creds.json")
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
drive_service = build('drive', 'v3', credentials=creds)


def download_image_from_drive(file_id, folder_name, file_name):
    """Download an image from Google Drive and save it locally."""
    try:
        request = drive_service.files().get_media(fileId=file_id)
        full_folder_path = os.path.join("static/images", folder_name)
        os.makedirs(full_folder_path, exist_ok=True)  # Ensure the listing folder exists

        file_path = os.path.join(full_folder_path, file_name)
        with open(file_path, 'wb') as file:
            file.write(request.execute())

        logger.info(f"Downloaded: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return None


def download_images_from_drive_folder(folder_id, folder_name):
    """Download all images from a Google Drive folder."""
    try:
        logger.debug(f"Attempting to download images from folder: {folder_name} ({folder_id})")

        # Check if the folder already exists locally
        full_folder_path = os.path.join("static/images", folder_name)
        if os.path.exists(full_folder_path):
            logger.info(f"Folder already exists locally: {full_folder_path}")
            # Return existing image paths
            image_paths = [
                os.path.join(full_folder_path, f)
                for f in os.listdir(full_folder_path)
                if f.endswith('.jpg')
            ]
            return image_paths

        # Test folder access
        query = f"'{folder_id}' in parents and mimeType contains 'image/'"
        logger.debug(f"Query: {query}")
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])

        logger.debug(f"Files found: {files}")

        if not files:
            logger.info(f"No images found in folder {folder_name} ({folder_id})")
            return []

        # Create the folder locally
        os.makedirs(full_folder_path, exist_ok=True)

        # Download images
        image_paths = []
        for idx, file in enumerate(files, start=1):
            file_id = file['id']
            file_name = f"image_{idx}.jpg"
            logger.debug(f"Downloading file: {file_name} (ID: {file_id})")
            image_path = download_image_from_drive(file_id, folder_name, file_name)
            if image_path:
                image_paths.append(image_path)

        return image_paths
    except Exception as e:
        logger.error(f"Skipping folder {folder_name} due to error: {e}")
        return []
