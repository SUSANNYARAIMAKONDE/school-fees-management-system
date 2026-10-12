
from getpass import getpass
from werkzeug.security import generate_password_hash

from database import get_db_connection


def create_admin():
    print("Maconte School - Create Staff Account")

    username = input("Enter username: ").strip()
    full_name = input("Enter full name: ").strip()
    password = getpass("Create password: ")
    confirm_password = getpass("Confirm password: ")

    if not username or not full_name or not password:
        print("All fields are required.")
        return

    if password != confirm_password:
        print("The passwords do not match.")
        return

    if len(password) < 10:
        print("Use a password with at least 10 characters.")
        return

    password_hash = generate_password_hash(password)

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (%s, %s, %s, %s)
            """,
            (username, password_hash, full_name, "admin")
        )

        connection.commit()
        print("Administrator account created successfully.")

    except Exception as error:
        connection.rollback()
        print("Could not create the account. Check whether the username already exists.")
        print("Technical details:", error)

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    create_admin()