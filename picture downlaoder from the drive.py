import os
import re
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Setup Google Sheets API
scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name("/Users/macbookprom3/Desktop/Web development/settler website/creds.json", scope)
client = gspread.authorize(creds)

# Access the worksheet
worksheet = client.open("upload sandbox 2").worksheet("Sheet1")

# Regular expression to match Google Drive file ID and extract folder name from the first link in column A
url_pattern = re.compile(r'https://drive\.google\.com/file/d/([^\s/]+)/')
folder_name_pattern = re.compile(r'ss\.ge/.*-(\d+)$')

# Base directory to store the images
base_dir = "/Users/macbookprom3/Desktop/Web development/settler website/listing pictures"  # Update this to your desired download location

# Function to download image
def download_image(url, folder_name, file_name):
    response = requests.get(url)
    if response.status_code == 200:
        full_folder_path = os.path.join(base_dir, folder_name)
        if not os.path.exists(full_folder_path):
            os.makedirs(full_folder_path)
        file_path = os.path.join(full_folder_path, file_name)
        with open(file_path, 'wb') as file:
            file.write(response.content)
        print(f"Downloaded: {file_path}")
    else:
        print(f"Failed to download image from {url}")

# Function to download images from a specified row
def download_images_from_row(start_row):
    # Iterate through the rows in the worksheet starting from the specified row
    rows = worksheet.get_all_values()
    for row in rows[start_row - 1:]:  # Adjust for 0-based index
        # Extract folder name from the first link in column A
        folder_match = folder_name_pattern.search(row[0])
        if folder_match:
            folder_name = folder_match.group(1)
            img_num = 1
            for cell in row[5:]:  # Start checking from column F (index 5) to the right
                match = url_pattern.match(cell)
                if match:
                    file_id = match.group(1)
                    download_url = f"https://drive.google.com/uc?export=view&id={file_id}"
                    download_image(download_url, folder_name, f"image_{img_num}.jpg")
                    img_num += 1

    print("Download completed.")

# Specify the row from which to start downloading
start_row = 168  # Change this to the desired starting row number
download_images_from_row(start_row)