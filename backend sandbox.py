import os
import re
import json
import gspread
import logging
from flask import Flask, render_template, request, url_for
from oauth2client.service_account import ServiceAccountCredentials

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

creds_path = os.getenv('GOOGLE_CLOUD_CREDENTIALS') or config.get('creds_path')


def initialize_sheets():
    """Initialize Google Sheets API and return worksheets."""
    filtered_worksheet = None
    complete_worksheet = None

    if not os.path.exists(creds_path):
        logger.error("The creds.json file does not exist at the specified path")
    else:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
            client = gspread.authorize(creds)
            filtered_worksheet = client.open("upload sandbox 2").worksheet("Sheet1")
            complete_worksheet = client.open("Owners may sandbox").worksheet("owner listings")
        except Exception as e:
            logger.error(f"An error occurred: {e}")

    return filtered_worksheet, complete_worksheet


def get_links(worksheet):
    """Get links from the worksheet."""
    if worksheet is None:
        logger.error("Worksheet is not initialized.")
        return []
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


def extract_attributes(complete_worksheet, filtered_worksheet, links):
    """Extract attributes for the given links."""
    listings = []
    if complete_worksheet is None or filtered_worksheet is None:
        logger.error("Worksheets are not initialized.")
        return listings
    complete_rows = complete_worksheet.get_all_values()
    filtered_rows = filtered_worksheet.get_all_values()

    descriptions = {normalize_link(row[0]): row[1] for row in filtered_rows}
    prices = {normalize_link(row[0]): row[5] for row in filtered_rows}

    for link in links:
        found = False
        for row in complete_rows:
            normalized_row_link = normalize_link(row[4])
            if normalized_row_link == link:
                description = descriptions.get(link, '')
                price = prices.get(link, '')
                if not price:
                    price = row[2]
                listing_id = re.search(r'\d+$', link).group()
                base_path = "static/images"
                image_folder = os.path.join(base_path, listing_id)
                logger.info(f"Base directory: {os.path.abspath(base_path)}")
                logger.info(f"Listing ID: {listing_id}")
                logger.info(f"Constructed image folder path: {os.path.abspath(image_folder)}")

                images = os.listdir(image_folder) if os.path.exists(image_folder) else []
                image_filename = images[0] if images else 'no_image_available.jpg'
                listing = {
                    "link": link,
                    "district": row[0],
                    "description": description,
                    "bedrooms": row[1],
                    "price": price,
                    "area": row[3],
                    "image_filename": image_filename,
                    "bathrooms": row[6],
                    "renovation": row[7],
                    "build_period": row[8],
                    "listing_id": listing_id,
                }
                logger.info(f"Matched listing: {listing}")
                listings.append(listing)
                found = True
                break
        if not found:
            logger.warning(f"No match found for link: {link}")
    return listings


def normalize_link(link):
    """Normalize links by extracting the part after 'ss.ge'."""
    match = re.search(r'ss.ge/(.*)', link)
    normalized = match.group(1) if match else link
    logger.debug(f"Normalized link: {normalized}")
    return normalized


# Initialize global listings variable
listings = []


def initialize_listings():
    """Initialize the listings data."""
    global listings
    if 'listings' in globals() and listings:
        # If listings are already initialized, don't reload them
        return

    filtered_worksheet, complete_worksheet = initialize_sheets()
    if filtered_worksheet and complete_worksheet:
        filtered_links = get_links(filtered_worksheet)
        logger.info(f"Filtered links: {filtered_links}")
        listings = extract_attributes(complete_worksheet, filtered_worksheet, filtered_links)
        logger.info(f"Extracted listings: {listings}")
    else:
        listings = []


def filter_listings(listings, area=None, price_min=None, price_max=None, bedrooms=None, district=None):
    """Filter listings based on area, price range, number of bedrooms, and district."""

    filtered_listings = []
    selected_districts = district if isinstance(district, list) else [district] if district else []

    for listing in listings:
        listing['image_url'] = url_for('static',
                                       filename=f'images/{listing["listing_id"]}/{listing.get("image_filename", "no_image_available.jpg")}')
        listing_price = parse_price(listing['price'])
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


@app.route('/test')
def index():
    """Render the index page without filters.doesnt contain filters"""
    global listings
    if not listings:
        initialize_listings()
    for listing in listings:
        listing['image_url'] = url_for('static',
                                       filename=f'images/{listing["listing_id"]}/{listing.get("image_filename", "no_image_available.jpg")}')
    return render_template('index.html', listings=listings)


def parse_price(price_str):
    """Remove commas, spaces, and convert to float."""
    try:
        return float(price_str.replace(',', '').replace('$', '').replace(' ', ''))
    except ValueError:
        return float('inf')


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
    districts = request.args.getlist('district')  # Use getlist to capture all selected districts

    distinct_districts = sorted(set(listing['district'] for listing in listings if listing['district'].strip()))

    filtered_listings = filter_listings(listings, area, price_min, price_max, bedrooms, districts)

    filters_applied = any([area, price_min, price_max, bedrooms, districts])

    if not filters_applied:
        hot_offers = sorted(listings, key=lambda x: parse_price(x['price']), reverse=True)[:9]
        for listing in hot_offers:
            listing['image_url'] = url_for('static',
                                           filename=f'images/{listing["listing_id"]}/{listing.get("image_filename", "no_image_available.jpg")}')
        return render_template('landing page with filter.html', listings=hot_offers, districts=distinct_districts,
                               show_hot_offers=True)

    for listing in filtered_listings:
        listing['image_url'] = url_for('static',
                                       filename=f'images/{listing["listing_id"]}/{listing.get("image_filename", "no_image_available.jpg")}')

    return render_template('landing page with filter.html', listings=filtered_listings, districts=distinct_districts,
                           show_hot_offers=False)


@app.route('/listing/<listing_id>')
def listing_detail(listing_id):
    """Render the detail page for a specific listing."""
    if 'listings' not in globals():
        initialize_listings()
    listing = next((item for item in listings if item["listing_id"] == listing_id), None)
    if listing:
        if listing['image_filename']:
            listing['image_url'] = url_for('static',
                                           filename=f'images/{listing["listing_id"]}/{listing["image_filename"]}')
        else:
            listing['image_url'] = url_for('static', filename='images/no_image_available.jpg')
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


if __name__ == '__main__':
    app.run(debug=True)
