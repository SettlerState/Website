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


def normalize_link(link):
    """Normalize links by extracting the part after 'ss.ge'."""
    match = re.search(r'ss.ge/(.*)', link)
    normalized = match.group(1) if match else link
    logger.debug(f"Normalized link: {normalized}")
    return normalized


def normalize_price(price_str):
    """Normalize the price string by removing currency symbols and formatting."""
    try:
        return float(price_str.replace('$', '').replace(' ', '').replace(',', ''))
    except ValueError:
        logger.error(f"Invalid price format: {price_str}")
        return None


def extract_attributes(complete_worksheet, filtered_worksheet, links):
    listings = []
    if complete_worksheet is None or filtered_worksheet is None:
        logger.error("Worksheets are not initialized.")
        return listings

    complete_rows = complete_worksheet.get_all_values()
    filtered_rows = filtered_worksheet.get_all_values()

    description_col = 1
    discounted_price_col = 3
    original_price_col = 2

    descriptions = {normalize_link(row[0]): row[description_col] for row in filtered_rows}
    discounted_prices = {normalize_link(row[0]): row[discounted_price_col] for row in filtered_rows}
    original_prices = {normalize_link(row[4]): row[original_price_col] for row in complete_rows}

    for link in links:
        found = False
        for row in complete_rows:
            normalized_row_link = normalize_link(row[4])
            if normalized_row_link == link:
                description = descriptions.get(link, 'Description not available')
                discounted_price = discounted_prices.get(link, 'Price not available')
                original_price = original_prices.get(link, 'Original price not available')

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

                listing_id_match = re.search(r'\d+$', link)
                if not listing_id_match:
                    logger.error(f"Invalid link format, cannot extract listing ID: {link}")
                    continue

                listing_id = listing_id_match.group()

                base_path = "static/images"
                image_folder = os.path.join(base_path, listing_id)
                images = os.listdir(image_folder) if os.path.exists(image_folder) else []
                image_filenames = [os.path.join(f'images/{listing_id}', image).replace('\\', '/') for image in images]
                if not images:
                    image_filenames = ['images/no_image_available.jpg']

                thumbnail_url = image_filenames[0] if image_filenames else 'images/no_image_available.jpg'

                listing = {
                    "link": link,
                    "district": row[0] if len(row) > 0 else '',
                    "description": description,
                    "bedrooms": row[1] if len(row) > 1 else '0',
                    "original_price": original_price_str,
                    "discounted_price": show_price,
                    "discount_amount": discount_str,
                    "area": row[3] if len(row) > 3 else '0',
                    "image_urls": [url_for('static', filename=image) for image in image_filenames],
                    "thumbnail_url": url_for('static', filename=thumbnail_url),
                    "bathrooms": row[6] if len(row) > 6 else '0',
                    "renovation": row[7] if len(row) > 7 else 'N/A',
                    "build_period": row[8] if len(row) > 8 else 'N/A',
                    "listing_id": listing_id,
                }

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

    filtered_worksheet, complete_worksheet = initialize_sheets()  # Expect 3 values now

    if filtered_worksheet and complete_worksheet:
        filtered_links = get_links(filtered_worksheet)
        logger.info(f"Filtered links: {filtered_links}")
        listings.extend(extract_attributes(complete_worksheet, filtered_worksheet, filtered_links))
        logger.info(f"Extracted listings: {listings}")
    else:
        listings = []


def filter_listings(listings, area=None, price_min=None, price_max=None, bedrooms=None, district=None):
    """Filter listings based on area, price range, number of bedrooms, and district."""

    filtered_listings = []
    selected_districts = district if isinstance(district, list) else [district] if district else []

    for listing in listings:
        listing['image_url'] = listing['image_urls'][0] if listing.get("image_urls") else url_for('static',
                                                                                                  filename='images/no_image_available.jpg')
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


@app.route('/test')
def test_index():
    """Render the index page without filters. Doesn't contain filters."""
    global listings
    if not listings:
        initialize_listings()
    for listing in listings:
        listing['image_urls'] = [url_for('static', filename=f'images/{listing["listing_id"]}/{img}') for img in
                                 os.listdir(os.path.join('static', 'images', listing['listing_id']))] if os.path.exists(
            os.path.join('static', 'images', listing['listing_id'])) else [
            url_for('static', filename='images/no_image_available.jpg')]
    return render_template('index.html', listings=listings)


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

    filtered_listings = filter_listings(listings, area, price_min, price_max, bedrooms, districts)

    filters_applied = any([area, price_min, price_max, bedrooms, districts])

    if not filters_applied:
        # Filter to get only discounted listings
        discounted_listings = [listing for listing in listings
                               if
                               listing['original_price'] and listing['discounted_price'] != listing['original_price']]
        # Sort by discounted price
        hot_offers = sorted(discounted_listings, key=lambda x: parse_price(x['discounted_price']), reverse=True)[:9]
        return render_template('landing page with filter.html', listings=hot_offers, districts=distinct_districts,
                               show_hot_offers=True)

    return render_template('landing page with filter.html', listings=filtered_listings, districts=distinct_districts,
                           show_hot_offers=False)


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


if __name__ == '__main__':
    app.run(debug=True)
