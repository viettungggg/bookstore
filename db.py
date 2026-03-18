import mysql.connector
from mysql.connector import pooling
import os

db_config = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get( "DB_PASSWORD", "password"),
    "database": os.environ.get("DB_NAME", "bookstore"),
    "port": int(os.environ.get("DB_PORT", 3306)),
}

connection_pool = pooling.MySQLConnectionPool(
    pool_name="bookstore_pool",
    pool_size=5,
    **db_config
)

def get_conn():
    return connection_pool.get_connection()
