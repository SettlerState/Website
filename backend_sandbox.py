import os
import re
import json
import gspread
import logging
import requests
from flask import Flask, render_template, request, url_for, send_from_directory
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from celery_worker import download_images_from_drive_folder_async
from utils import download_images_from_drive_folder

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup Google Sheets API
scope = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Initialize Flask app
app = Flask(__name__)
with open('config.json') as config_file:
    config = json.load(config_file)
# creds_path = os.getenv('GOOGLE_CLOUD_CREDENTIALS') or config.get('creds_path')

# creds_path = r'/mnt/c/Users/Lenovo/PycharmProjects/Website/creds.json'
creds_path = os.path.expanduser("/home/tatuliusi/production/secrets/creds.json")

# Global variables
listings = []
IMAGE_CACHE_DIR = "static/images"  # Base directory for cached images
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)  # Ensure the cache directory exists

# Regular expression to extract folder ID from Google Drive links to handle both formats
folder_id_pattern = re.compile(r"https://drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)(?:\?.*)?")

# Initialize Google Drive API
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
drive_service = build('drive', 'v3', credentials=creds)


def initialize_sheets():
    """Initialize Google Sheets API and return worksheets."""
    full_worksheet = None
    if not os.path.exists(creds_path):
        logger.error("The creds.json file does not exist at the specified path")
    else:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
            client = gspread.authorize(creds)
            full_worksheet = client.open("Owners - December backup").worksheet("owner listings")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
    return full_worksheet


def get_links(worksheet):
    """Get links from the worksheet."""
    if worksheet is None:
        logger.error("Worksheet is not initialized.")
        return []
    url_pattern = re.compile(r'https?://[^\s]+')
    rows = worksheet.get_all_values()
    links = []
    for row in rows:
        cell_value = row[5]  # links are in the fifth column
        if cell_value and url_pattern.match(cell_value):
            normalized_link = normalize_link(cell_value)
            links.append(normalized_link)
            logger.info(f"Extracted and normalized link: {normalized_link}")
    return links


def normalize_link(link):
    """Normalize links by extracting the part after 'ss.ge' and also 'myhome.ge'."""
    match = re.search(r'(?:ss\.ge|myhome\.ge)/(.+)', link)
    normalized = match.group(1) if match else link
    logger.debug(f"Normalized link: {normalized}")
    return normalized


def normalize_folder_link(folder_link):
    """Normalize the folder link by extracting the folder ID."""
    folder_match = folder_id_pattern.search(folder_link)
    if folder_match:
        folder_id = folder_match.group(1)
        return folder_id
    return None


def normalize_price(price_str):
    """Normalize the price string by removing currency symbols and formatting."""
    if not price_str or not price_str.strip():
        return None  # Return None for empty or invalid price values
    try:
        return float(price_str.replace('$', '').replace(' ', '').replace(',', ''))
    except ValueError:
        logger.error(f"Invalid price format: {price_str}")
        return None


def extract_attributes(full_worksheet, links):
    listings = []
    if full_worksheet is None:
        logger.error("Worksheets are not initialized.")
        return listings

    full_rows = full_worksheet.get_all_values()

    description_col = 13
    discounted_price_col = 12
    original_price_col = 3
    floors_col = 7
    id_col = 0  # Column A for the 4-digit ID
    add_time_col = 11
    drive_link_col = 16  # Column Q for Google Drive folder links

    for row in full_rows:
        # Extract the ID from the specific column
        listing_id = row[id_col].strip() if id_col < len(row) else None
        if not listing_id or not re.match(r'^\d{6}$', listing_id):
            continue  # Skip rows without valid IDs

        # Check for valid Drive link first
        folder_link = row[drive_link_col] if len(row) > drive_link_col else ''
        if not folder_link:
            continue  # Skip listings without Drive links

        folder_id = normalize_folder_link(folder_link)
        if not folder_id:
            continue  # Skip listings with invalid Drive links

        # Extract other attributes
        link = normalize_link(row[5]) if len(row) > 5 else ''
        description = row[description_col].strip() if len(row) > description_col else 'Description not available'
        discounted_price = row[discounted_price_col].strip() if len(row) > discounted_price_col else (
            'Price not available')
        original_price = row[original_price_col].strip() if len(row) > original_price_col else (
            'Original Price not available')
        date_time = row[add_time_col].strip() if len(row) > add_time_col else 'Date not available'

        # Normalize prices
        normalized_discounted_price = normalize_price(discounted_price)
        normalized_original_price = normalize_price(original_price)

        # Calculate the discount amount
        discount_amount = None
        if normalized_discounted_price and normalized_original_price:
            discount_amount = normalized_original_price - normalized_discounted_price if normalized_original_price > normalized_discounted_price else None

        # Handle price comparison and formatting
        if normalized_discounted_price is None or normalized_discounted_price == normalized_original_price:
            show_price = f"{normalized_original_price:,.0f}" if normalized_original_price else 'ფასი შეთანხმებით'
            original_price_str = ""  # Hide original if no discount
        else:
            show_price = f"{normalized_discounted_price:,.0f}" if normalized_discounted_price else 'Price not available'
            original_price_str = f"{normalized_original_price:,.0f}" if normalized_original_price else ""

        if isinstance(original_price_str, str) and original_price_str.endswith('.0'):
            original_price_str = original_price_str[:-2]
        if isinstance(show_price, str) and show_price.endswith('.0'):
            show_price = show_price[:-2]

        discount_str = f"{discount_amount:,.0f}" if discount_amount and discount_amount > 0 else ""

        # Handle image paths
        folder_name = f"myhome.ge_{listing_id}_დამუშავებული"
        logger.debug(f"Attempting to access folder: {folder_name} ({folder_id})")

        # Check if images are already downloaded
        full_folder_path = os.path.join(IMAGE_CACHE_DIR, folder_name)
        if os.path.exists(full_folder_path):
            image_urls = [
                url_for('static', filename=os.path.relpath(
                    os.path.join(full_folder_path, f), 'static'
                ).replace('\\', '/'))
                for f in os.listdir(full_folder_path)
                if f.endswith('.jpg')
            ]
        else:
            # Trigger the Celery task to download images asynchronously
            download_images_from_drive_folder_async.delay(folder_id, folder_name)
            image_urls = [url_for('static', filename='images/no_image_available.jpg')]

        thumbnail_url = image_urls[0] if image_urls else url_for('static', filename='images/no_image_available.jpg')

        # Add the listing to the list
        listing = {
            "link": link,
            "district": row[1] if len(row) > 1 else '',
            "description": description,
            "bedrooms": row[2] if len(row) > 2 else '0',
            "original_price": original_price_str,
            "discounted_price": show_price,
            "discount_amount": discount_str,
            "area": row[4] if len(row) > 4 else '0',
            "image_urls": image_urls,
            "thumbnail_url": thumbnail_url,
            "floors": row[floors_col] if len(row) > floors_col else "N/A",
            "bathrooms": row[7] if len(row) > 7 and row[7].isdigit() else '1',
            "build_period": row[8] if len(row) > 8 else 'N/A',
            "renovation": row[9] if len(row) > 9 else 'N/A',
            "listing_id": listing_id,
            "date_time": date_time,
        }

        listings.append(listing)

    return listings


# Initialize global listings variable
listings = []


def initialize_listings():
    """Initialize the listings data."""
    global listings
    if 'listings' in globals() and listings:
        # If listings are already initialized, don't reload them
        return

    full_worksheet = initialize_sheets()

    if full_worksheet:
        full_links = get_links(full_worksheet)
        logger.info(f"Filtered links: {full_links}")
        listings.extend([l for l in extract_attributes(full_worksheet, full_links) if l['listing_id']])
        logger.info(f"Extracted listings: {listings}")
    else:
        listings = []


def filter_listings(listings, area=None, price_min=None, price_max=None, bedrooms=None, district=None):
    """Filter listings based on area, price range, number of bedrooms, and district."""

    filtered_listings = []
    selected_districts = district if isinstance(district, list) else [district] if district else []

    for listing in listings:
        listing['image_url'] = listing['image_urls'][0] if listing.get("image_urls") else url_for('static',
                                                                                                  filename='images'
                                                                                                           '/no_image_available.jpg')
        listing_price = parse_price(listing['discounted_price'])
        min_price = parse_price(price_min) if price_min else None
        max_price = parse_price(price_max) if price_max else None

        try:
            listing_bedrooms = int(listing['bedrooms'])
        except ValueError:
            listing_bedrooms = None

        if bedrooms and str(bedrooms).isdigit():
            bedrooms = int(bedrooms)
        else:
            bedrooms = None

        # Check if the listing matches all the filter criteria
        if (area and area.lower() not in listing['district'].lower()) or \
                (min_price is not None and listing_price < min_price) or \
                (max_price is not None and listing_price > max_price) or \
                (bedrooms is not None and listing_bedrooms != bedrooms) or \
                (selected_districts and listing['district'].lower() not in map(str.lower, selected_districts)):
            continue
        filtered_listings.append(listing)
    return filtered_listings


def parse_price(price_str):
    """Remove commas, spaces, and convert to float."""
    try:
        return float(price_str.replace(',', '').replace('$', '').replace(' ', ''))
    except ValueError:
        return float('inf')


def get_page_range(current_page, total_pages):
    page_range = []

    # If we're on a higher page, show the first few pages and ellipsis
    if current_page > 3:
        page_range.append(1)  # First page
        page_range.append("...")  # Ellipsis

    # Show pages around the current page
    for i in range(max(1, current_page - 1), min(current_page + 2, total_pages) + 1):
        page_range.append(i)

    # If we're not on the last few pages, show ellipsis and the last page
    if current_page < total_pages - 2:
        page_range.append("...")
        page_range.append(total_pages)  # Last page

    return page_range


@app.route('/', methods=['GET'])
def landing():
    global listings
    if not listings:
        initialize_listings()

    # Get filter criteria from query parameters
    area = request.args.get('area')
    price_min = request.args.get('price_min')
    price_max = request.args.get('price_max')
    bedrooms = request.args.get('bedrooms')
    districts = request.args.getlist('district')

    distinct_districts = sorted(set(listing['district'] for listing in listings if listing['district'].strip()))

    # Identify hot offers (listings with a discount)
    hot_offers = [listing for listing in listings if
                  listing['discounted_price'] and listing['discounted_price'] != listing['original_price']]

    # Check if filters are applied (to determine if we should show hot offers)
    filters_applied = any([area, price_min, price_max, bedrooms, districts])

    # Filter listings based on search criteria
    filtered_listings = filter_listings(listings, area, price_min, price_max, bedrooms, districts)

    # Pagination parameters
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=12, type=int)  # Default to 12 listings per page

    # Calculate total pages
    total_listings = len(filtered_listings)
    total_pages = max(1, (total_listings + per_page - 1) // per_page)

    # Ensure page is within bounds
    page = max(1, min(page, total_pages))

    # Slice listings for the current page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_listings = filtered_listings[start_idx:end_idx]

    # Pagination metadata
    pagination = {
        "current_page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < total_pages else None
    }

    pagination_range = get_page_range(page, total_pages)

    return render_template(
        'landing_page_with_filter.html',
        listings=paginated_listings,
        hot_offers=hot_offers if not filters_applied else [],  # Hide hot offers if filters exist
        districts=distinct_districts,
        show_hot_offers=not filters_applied,  # This should be False if filters exist
        pagination=pagination,
        pagination_range=pagination_range,
        filters_applied=filters_applied,
    )


@app.route('/listing/<listing_id>')
def listing_detail(listing_id):
    """Render the detail page for a specific listing."""
    if not listings:
        initialize_listings()
    listing = next((item for item in listings if item["listing_id"] == listing_id), None)
    if listing:
        logger.debug(f"Listing data: {listing}")  # Debugging line
        # Ensure 'image_urls' exists and is a list
        if 'image_urls' not in listing or not listing['image_urls']:
            listing['image_urls'] = [url_for('static', filename='images/no_image_available.jpg')]
        return render_template('listing_detail.html', listing=listing)
    else:
        return "Listing not found", 404


@app.route('/blog')
def blog():
    return render_template('blog.html')


@app.route('/test_env')
def test_env():
    creds_json = os.getenv('GOOGLE_CLOUD_CREDENTIALS')
    if creds_json:
        logger.info(f"Environment variable value: {creds_json}")
        return "Environment variable is set.", 200
    return "Environment variable is not set or empty.", 500


@app.route('/without')
def without_filter():
    global listings
    if not listings:
        initialize_listings()  # Ensure listings are loaded if not already initialized
    return render_template('without_filter.html', listings=listings)


if __name__ == '__main__':
    app.run(debug=True)
