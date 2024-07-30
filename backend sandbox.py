import os
import re
import gspread
import logging
from flask import Flask, render_template, url_for
from oauth2client.service_account import ServiceAccountCredentials

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup Google Sheets API
scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name("/Users/macbookprom3/Desktop/Web development/settler website/creds.json", scope)
client = gspread.authorize(creds)

# Access the worksheets
filtered_worksheet = client.open("upload sandbox 2").worksheet("Sheet1")
complete_worksheet = client.open("Owners may sandbox").worksheet("owner listings")

# Function to normalize links by extracting the part after 'ss.ge'
def normalize_link(link):
    match = re.search(r'ss.ge/(.*)', link)
    normalized = match.group(1) if match else link
    logger.debug(f"Normalized link: {normalized}")
    return normalized

# Function to check if a cell contains a link and print it if it does
def get_links(worksheet):
    url_pattern = re.compile(r'https?://[^\s]+')
    rows = worksheet.get_all_values()
    links = []
    for row in rows:
        cell_value = row[0]  # Assuming the links are in the first column
        if cell_value and url_pattern.match(cell_value):
            normalized_link = normalize_link(cell_value)
            links.append(normalized_link)
            logger.info(f"Extracted and normalized link: {normalized_link}")
    return links

# Function to find and extract attributes for the given links
def extract_attributes(complete_worksheet, filtered_worksheet, links):
    listings = []
    complete_rows = complete_worksheet.get_all_values()
    filtered_rows = filtered_worksheet.get_all_values()
    
    descriptions = {normalize_link(row[0]): row[1] for row in filtered_rows}  # Create a dictionary for descriptions
    prices = {normalize_link(row[0]): row[5] for row in filtered_rows}  # Create a dictionary for prices (column F)

    for link in links:
        found = False
        for row in complete_rows:
            normalized_row_link = normalize_link(row[4])  # Normalize the link in the row for matching
            if normalized_row_link == link:
                description = descriptions.get(link, '')  # Get the description from the dictionary
                price = prices.get(link, '')  # Get the price from the dictionary
                if not price:  # If the price is empty, use the price from the complete worksheet
                    price = row[2]  # Assuming the price is in column C of the complete worksheet
                listing_id = re.search(r'\d+$', link).group()  # Extract the listing ID
                
                # Construct path to images
                base_path = "static/images"
                image_folder = os.path.join(base_path, listing_id)
                logger.info(f"Base directory: {os.path.abspath(base_path)}")
                logger.info(f"Listing ID: {listing_id}")
                logger.info(f"Constructed image folder path: {os.path.abspath(image_folder)}")
                
                images = os.listdir(image_folder) if os.path.exists(image_folder) else []
                image_filename = images[0] if images else 'no_image_available.jpg'  # Get the first image if available
                listing = {
                    "link": link,
                    "district": row[0],
                    "description": description,  # Add description
                    "bedrooms": row[1],
                    "price": price,  # Use the price from the filtered worksheet or fallback to the complete worksheet
                    "area": row[3],
                    "image_filename": image_filename,  # Use the first image filename if available
                    "bathrooms": row[6],
                    "renovation": row[7],
                    "build_period": row[8],
                    "listing_id": listing_id,  # Include listing ID for URL construction
                }
                logger.info(f"Matched listing: {listing}")
                listings.append(listing)
                found = True
                break
        if not found:
            logger.warning(f"No match found for link: {link}")
    return listings

# Get the links from the filtered Google Sheet
filtered_links = get_links(filtered_worksheet)
logger.info(f"Filtered links: {filtered_links}")
print("ee")

# Extract attributes for the filtered links
listings = extract_attributes(complete_worksheet, filtered_worksheet, filtered_links)
logger.info(f"Extracted listings: {listings}")

# Flask application to display the listings
app = Flask(__name__)

@app.route('/')
def index():
    for listing in listings:
        if listing['image_filename']:
            listing['image_url'] = url_for('static', filename=f'images/{listing["listing_id"]}/{listing["image_filename"]}')
            logger.info(f"Constructed image URL: {listing['image_url']}")
        else:
            listing['image_url'] = url_for('static', filename='images/no_image_available.jpg')
    return render_template('index.html', listings=listings)

# New route for individual listings
@app.route('/listing/<listing_id>')
def listing_detail(listing_id):
    # Find the listing by listing_id
    listing = next((item for item in listings if item["listing_id"] == listing_id), None)
    if listing:
        if listing['image_filename']:
            listing['image_url'] = url_for('static', filename=f'images/{listing["listing_id"]}/{listing["image_filename"]}')
        else:
            listing['image_url'] = url_for('static', filename='images/no_image_available.jpg')
        return render_template('listing_detail.html', listing=listing)
    else:
        return "Listing not found", 404

if __name__ == '__main__':
    app.run(debug=True)