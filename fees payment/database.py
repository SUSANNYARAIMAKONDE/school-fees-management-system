
import mysql.connector


def get_db_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="Susan@2000",
        database="maconte_fees"
    )

    return connection