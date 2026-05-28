import psycopg2

from saleor.settings import BRAND_ORDER_DB_HOST, BRAND_ORDER_DB_NAME, BRAND_ORDER_DB_PASSWORD, BRAND_ORDER_DB_PORT, BRAND_ORDER_DB_USER


def get_brand_order_table_connection():
    connection = psycopg2.connect(user=BRAND_ORDER_DB_USER,
                                password=BRAND_ORDER_DB_PASSWORD,
                                host=BRAND_ORDER_DB_HOST,
                                port=BRAND_ORDER_DB_PORT,
                                database=BRAND_ORDER_DB_NAME)
    
    return connection