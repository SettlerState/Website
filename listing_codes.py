import os
from apscheduler.schedulers.background import BackgroundScheduler
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Constants
LAST_ID_CELL = 'R1'  # Cell to store the last assigned ID
ID_LENGTH = 6  # 6-digit IDs
START_ID = 100000  # Starting ID for the first listing


def authorize_sheets(creds_file, sheet_name):
    """Authorize and connect to the Google Sheet."""
    scope = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name).worksheet('owner listings')
    return sheet


def get_last_assigned_id(sheet):
    """Retrieve the last assigned ID from the Google Sheet."""
    try:
        last_id = sheet.acell(LAST_ID_CELL).value
        print(f"Retrieved last assigned ID from R1: {last_id}")
        return int(last_id) if last_id else START_ID  # Start from START_ID if no ID exists
    except Exception as e:
        print(f"Error retrieving last assigned ID from R1: {e}")
        return START_ID  # Default starting ID


def update_last_assigned_id(sheet, new_id):
    """Update the last assigned ID in the Google Sheet."""
    try:
        print(f"Updating last assigned ID in cell {LAST_ID_CELL} with value: {new_id}")
        sheet.update([[new_id]], LAST_ID_CELL)  # Updated syntax: values first, range_name second
        print("Last assigned ID updated successfully.")
    except Exception as e:
        print(f"Error updating last assigned ID: {e}")


def get_highest_existing_id(records):
    """Retrieve the highest existing ID from the records."""
    existing_ids = [int(record.get('იდენტიფიკატორი', 0)) for record in records if record.get('იდენტიფიკატორი')]
    return max(existing_ids) if existing_ids else START_ID


def assign_ascending_ids(creds_file, sheet_name):
    """Assign ascending 6-digit IDs to listings where 'თანამშრომლობს' equals 1."""
    try:
        expected_headers = [
            'იდენტიფიკატორი', 'თანამშრომლობს'
        ]
        sheet = authorize_sheets(creds_file, sheet_name)
        records = sheet.get_all_records(expected_headers=expected_headers)

        # Get the last assigned ID from R1 or the highest existing ID in the sheet
        last_id = get_last_assigned_id(sheet)
        highest_existing_id = get_highest_existing_id(records)
        last_id = max(last_id, highest_existing_id)
        print(f"Starting ID: {last_id}")

        updates = []
        for i, record in enumerate(records, start=2):  # Start at row 2 (1-based index in Sheets)
            collaboration_value = record.get('თანამშრომლობს', None)
            existing_id = record.get('იდენტიფიკატორი', None)
            print(f"Row {i}: Collaboration value = {collaboration_value}, Existing ID = {existing_id}")

            if collaboration_value == 1 and not existing_id:  # Check if ID assignment is needed
                last_id += 1  # Increment the last assigned ID
                new_id = str(last_id).zfill(ID_LENGTH)  # Ensure 6-digit format
                id_col_index = list(record.keys()).index('იდენტიფიკატორი') + 1
                updates.append({
                    'range': f'{gspread.utils.rowcol_to_a1(i, id_col_index)}',
                    'values': [[new_id]]
                })
                print(f"Assigned new ID: {new_id} to row {i}")

        # Update R1 with the highest ID (even if no new IDs are assigned)
        update_last_assigned_id(sheet, last_id)

        if updates:
            print(f"Updates to be applied: {updates}")
            print(f"Updating {len(updates)} rows with new IDs.")
            sheet.batch_update(updates)
        else:
            print("No new IDs to assign.")
    except gspread.exceptions.APIError as e:
        print(f'Quota exceeded: {e}')
    except Exception as e:
        print(f'An error occurred: {e}')


if __name__ == '__main__':
    #creds_file = 'creds.json'  # Path to Google service account credentials
    creds_file = os.path.expanduser("/home/settleradmin/production/Website/creds.json")
    sheet_name = 'owners - 14 may'

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        assign_ascending_ids,
        'interval',
        minutes=30,
        id='code_assignment',
        kwargs={'creds_file': creds_file, 'sheet_name': sheet_name},
        misfire_grace_time=3600
    )
    scheduler.start()
    print('Scheduler running in background')
    assign_ascending_ids(creds_file, sheet_name)
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print('Scheduler stopped')
