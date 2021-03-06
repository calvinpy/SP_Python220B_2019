'''
This file contains functions for converting CSV data to a MongoDB database
'''
import os
import csv
import json
import logging
import time
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

LOG_FORMAT = '%(asctime)s %(filename)s:%(lineno)-3d %(levelname)s %(message)s'
FORMATTER = logging.Formatter(LOG_FORMAT)

# Create log file for warning and error messages
LOG_FILE = 'db.log'
FILE_HANDLER = logging.FileHandler(LOG_FILE)
FILE_HANDLER.setLevel(logging.INFO)
FILE_HANDLER.setFormatter(FORMATTER)
# Add handlers to logger
LOGGER.addHandler(FILE_HANDLER)

class MongoDBConnection():
    """MongoDB Connection"""
    def __init__(self, host='127.0.0.1', port=27017):
        """ be sure to use the ip address not name for local windows"""
        self.host = host
        self.port = port
        self.connection = None

    def __enter__(self):
        self.connection = MongoClient(self.host, self.port)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.close()

def create_mongo_connection(host='127.0.0.1', port=27017):
    '''
    Method to create mongo DB connection, allows user to change host or port
    from default values
    '''
    return MongoDBConnection(host, port)

def system_diagnostics(func):
    '''
    Decorator to time and report diagnostics on CSV read and MongoDB methods
    Each function call is logged in terms of elapsed time, which function was
    called, and how many records were processed
    '''
    def inner(*args, **kwargs):
        # Record elapsed time for function call
        ts = time.time()
        result = func(*args, **kwargs)
        te = time.time()
        elapsed = te - ts
        # First result is either list or int, if list, get length to retrieve
        # number of records processed
        if type(result[0]).__name__ == 'list':
            records = len(result[0])
        else:
            records = result[0]
        with open('timings.txt', 'a') as timefile:
            timefile.write('function \'{}\' called, input = {}, \
time = {:f} seconds, {} records processed\n'.format(func.__name__,
                                                    args[-1],
                                                    elapsed,
                                                    records))
        return result
    return inner

@system_diagnostics
def import_csv_to_json(csv_file):
    '''
    Method to convert a csv file to a JSON string object
    Args:
        csv_file (string):
            CSV file to read
    Returns:
        json_list (JSON):
            JSON formatted string representation of CSV file contents.
            Each string is a series of key/values pairs representing a row
            from the csv file (key = csv column header, value = row value)
        errors (int):
            Number of errors encountered during CSV read
    '''
    json_list = []
    errors = 0
    try:
        LOGGER.info(f'Reading file \'{csv_file}\'')
        with open(csv_file) as filex:
            json_list = [json.loads(json.dumps(row)) for row in csv.DictReader(filex)]
    except (FileNotFoundError, IOError) as ERR:
        LOGGER.error(f'Could not read {csv_file}. Check file existence and/or permissions.')
        LOGGER.error(f'Error message: {ERR}')
        errors += 1
    return json_list, errors

@system_diagnostics
def add_json_to_mongodb(json_data, db_name, mongo=None):
    '''
    Method to add JSON formatted data to a mongo database
    Args:
        json_data (JSON):
            A list of JSON formatted data
        db_name (str):
            Mongo database name
    Returns:
        collection_count (int):
            Count of documents added to the database
        error_count (int):
            Count of errors generated during document add
    '''
    # Create mongo database connection if not provided
    if not mongo:
        mongo = create_mongo_connection()

    errors = 0
    try:
        with mongo:
            LOGGER.info('Creating mongo connection')
            db = mongo.connection.HPNorton
            LOGGER.info(f'Creating {db_name} database and adding records')
            new_db = db[db_name]
            new_db.insert_many(json_data)
            collection_count = new_db.estimated_document_count()
    except (ConnectionFailure, ServerSelectionTimeoutError) as CF: # MongoDB connection issue
        LOGGER.error('Could not connect to MongoDB database.')
        LOGGER.error(f'Error message: {CF}')
        collection_count = 0
        errors += 1

    return collection_count, errors

def import_data(directory_name, product_file, customer_file, rentals_file):
    '''
    Method to import CSV data and add to a mongo database
    Args:
        directory_name (str):
            Directory where CSV files are located
            Pass empty string if files in current directory
        product_file (str):
            Name of CSV file containing product data
        customer_file (str):
            Name of CSV file containing customer data
        rentals_file (str):
            Name of CSV file containing rentals data
    Returns:
        counts (tuple):
            Count of documents added for the product, customer, and rentals
            database, in that order
        errors (tuple):
            Count of errors encountered while adding documents for the product,
            customer, and rentals database, in that order
    '''

    # Convert csv files to JSON data
    product_json, product_csv_errors = import_csv_to_json(
        os.path.join(directory_name, product_file))
    customer_json, customer_errors = import_csv_to_json(
        os.path.join(directory_name, customer_file))
    rentals_json, rentals_errors = import_csv_to_json(
        os.path.join(directory_name, rentals_file))

    # Add JSON data to mongo database
    product_count, product_db_errors = add_json_to_mongodb(product_json, 'product')
    customer_count, customer_db_errors = add_json_to_mongodb(customer_json, 'customer')
    rentals_count, rentals_db_errors = add_json_to_mongodb(rentals_json, 'rentals')

    counts = (product_count, customer_count, rentals_count)
    errors = (product_csv_errors + product_db_errors,
              customer_errors + customer_db_errors,
              rentals_errors + rentals_db_errors)

    return counts, errors

def show_available_products(mongo=None):
    '''
    Method to return a nested python dictionary of available products. Products
    with a quantity_available value of 0 are considered not available
    Returns:
        product_dict (dict):
            Nested python dictionary with key = product_id,
            value = python dictionary with description, product_type, and
            quantity_available keys, and associated values from product database
    '''
    # Create mongo database connection
    if not mongo:
        mongo = create_mongo_connection()

    product_dict = {}
    try:
        with mongo:
            LOGGER.info('Creating mongo connection')
            db = mongo.connection.HPNorton
            LOGGER.info(f'Querying product database for available products')
            # Filter query to return products with non-zero quanitity
            query = db['product'].find({'quantity_available': {'$ne':'0'}})
            for item in query:
                # Populate product dictionary
                product_dict[item['product_id']] = {'description':
                                                    item['description'],
                                                    'product_type':
                                                    item['product_type'],
                                                    'quantity_available':
                                                    item['quantity_available']}
    except (ConnectionFailure, ServerSelectionTimeoutError) as CF: # MongoDB connection issue
        LOGGER.error('Could not connect to MongoDB database.')
        LOGGER.error(f'Error message: {CF}')

    return product_dict

def show_rentals(product_id, mongo=None):
    '''
    Method to return data for customers that have rented products matching product_id
    Args:
        product_id (str):
            Product ID of interest
    Returns:
        rentals_dict (dict):
            Nested python dictionary with key = customer_id,
            value = python dictionary with name, address, phone_number and
            email keys, and associated values from customer database
    '''
    # Create mongo database connection
    if not mongo:
        mongo = create_mongo_connection()

    customers = []
    rentals_dict = {}
    try:
        with mongo:
            LOGGER.info('Creating mongo connection')
            db = mongo.connection.HPNorton
            LOGGER.info(f'Querying rentals database for customers renting product {product_id}')
            # Filter query to return customers who rented specific product
            query = db['rentals'].find({'product_id': {'$eq':product_id}})
            customers = [item['customer_id'] for item in query]
            customers.sort()
            # Filter query results to find relevant customer details
            query = db['customer'].find({'user_id': {'$in':customers}})
            for item in query:
                rentals_dict[item['user_id']] = {'name': item['name'],
                                                 'address': item['address'],
                                                 'phone_number': item['phone_number'],
                                                 'email': item['email']}
    except (ConnectionFailure, ServerSelectionTimeoutError) as CF: # MongoDB connection issue
        LOGGER.error('Could not connect to MongoDB database.')
        LOGGER.error(f'Error message: {CF}')

    return rentals_dict

def clear_database():
    '''
    Delete databases for testing
    '''
    # Clear database
    mongo = MongoDBConnection()
    with mongo:
        db = mongo.connection.HPNorton
        db['product'].drop()
        db['customer'].drop()
        db['rentals'].drop()

if __name__ == "__main__":
    # Run diagnostics on various sample sizes (10 through 100000 in powers of 10)
    os.remove('timings.txt')
    trials = [10**x for x in range(1, 6)]
    product_csv = 'products.csv'
    customer_csv = 'customers.csv'
    rentals_csv = 'rentals.csv'
    for trial in trials:
        clear_database()
        directory = 'sample_csv_files_{:d}'.format(trial)
        import_data(directory, product_csv, customer_csv, rentals_csv)
