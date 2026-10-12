
import os
from decimal import Decimal, InvalidOperation
from datetime import date

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session
)
from werkzeug.security import check_password_hash

from database import get_db_connection


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "Set the SECRET_KEY environment variable before starting Flask."
    )

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM users WHERE username = %s",
                (username,)
            )
            user = cursor.fetchone()

        except Exception:
            app.logger.exception("Login database error")
            flash("Unable to log in. Please try again.")
            return render_template("login.html"), 503

        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.")

    return render_template("login.html")



    
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Count registered students
        cursor.execute("SELECT COUNT(*) AS total FROM students")
        total_students = cursor.fetchone()["total"]

        # Calculate total payments collected
        cursor.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM payments")
        total_collected = cursor.fetchone()["total"]

        # Count payments recorded today
        cursor.execute(
            "SELECT COUNT(*) AS total FROM payments WHERE payment_date = %s",
            (date.today(),)
        )
        payments_today = cursor.fetchone()["total"]

        # Calculate outstanding balances
        cursor.execute("""
            SELECT COALESCE(SUM(balance), 0) AS total
            FROM (
                SELECT GREATEST(
                    sf.amount_due - COALESCE(p.total_paid, 0),
                    0
                ) AS balance
                FROM student_fees sf
                LEFT JOIN (
                    SELECT
                        student_id,
                        term,
                        YEAR(payment_date) AS payment_year,
                        SUM(amount) AS total_paid
                    FROM payments
                    GROUP BY student_id, term, YEAR(payment_date)
                ) p
                    ON p.student_id = sf.student_id
                    AND p.term = sf.term
                    AND p.payment_year =
                        CAST(sf.academic_year AS UNSIGNED)
            ) AS fee_balances
        """)
        outstanding_fees = cursor.fetchone()["total"]

    except Exception:
        app.logger.exception("Dashboard loading error")
        flash("Unable to load dashboard figures. Please check the database.")

        total_students = 0
        total_collected = Decimal("0.00")
        payments_today = 0
        outstanding_fees = Decimal("0.00")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        total_collected=total_collected,
        payments_today=payments_today,
        outstanding_fees=outstanding_fees
    )




@app.route("/students", methods=["GET", "POST"])
def students():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip() or None
        gender = request.form.get("gender", "").strip() or None
        class_name = request.form.get("class_name", "").strip()
        guardian_name = request.form.get("guardian_name", "").strip()
        guardian_phone = request.form.get("guardian_phone", "").strip()
        enrollment_date = request.form.get("enrollment_date", "").strip()

        if not all([
            first_name, last_name, class_name,
            guardian_name, guardian_phone, enrollment_date
        ]):
            flash("Please complete all required student fields.")
            return redirect(url_for("students"))

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO students (
                    first_name, last_name, date_of_birth, gender,
                    class_name, guardian_name, guardian_phone,
                    enrollment_date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    first_name, last_name, date_of_birth, gender,
                    class_name, guardian_name, guardian_phone,
                    enrollment_date
                )
            )
            connection.commit()
            flash("Student registered successfully.")

        except Exception:
            app.logger.exception("Student registration error")
            if connection is not None:
                connection.rollback()
            flash("Unable to register the student.")

        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        return redirect(url_for("students"))

    search = request.args.get("search", "").strip()
    connection = None
    cursor = None
    student_list = []

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if search:
            pattern = f"%{search}%"
            cursor.execute(
                """
                SELECT student_id, first_name, last_name, class_name,
                       guardian_name, guardian_phone, enrollment_date
                FROM students
                WHERE first_name LIKE %s
                   OR last_name LIKE %s
                   OR class_name LIKE %s
                ORDER BY last_name, first_name
                """,
                (pattern, pattern, pattern)
            )
        else:
            cursor.execute(
                """
                SELECT student_id, first_name, last_name, class_name,
                       guardian_name, guardian_phone, enrollment_date
                FROM students
                ORDER BY last_name, first_name
                """
            )

        student_list = cursor.fetchall()

    except Exception:
        app.logger.exception("Student listing error")
        flash("Unable to load student records.")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "students.html",
        students=student_list,
        search=search
    )


@app.route("/payments", methods=["GET", "POST"])
def payments():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        student_id_text = request.form.get("student_id", "").strip()
        amount_text = request.form.get("amount", "").strip()
        payment_date = request.form.get("payment_date", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        reference_number = (
            request.form.get("reference_number", "").strip() or None
        )
        term = request.form.get("term", "").strip()

        # Validate the student ID.
        try:
            student_id = int(student_id_text)
            if student_id <= 0:
                raise ValueError
        except ValueError:
            flash("Enter a valid student ID.")
            return redirect(url_for("payments"))

        # Validate the amount using Decimal to avoid float rounding issues.
        try:
            amount = Decimal(amount_text)
            if not amount.is_finite() or amount <= 0 or amount > Decimal("99999999.99"):
                raise ValueError
            amount = amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            flash("Enter a valid payment amount greater than zero.")
            return redirect(url_for("payments"))

        # Validate the date and allowed form options.
        try:
            valid_date = date.fromisoformat(payment_date)
            if valid_date > date.today():
                raise ValueError
        except ValueError:
            flash("Enter a valid payment date that is not in the future.")
            return redirect(url_for("payments"))

        if payment_method not in ("Cash", "Bank Transfer", "Mobile Money"):
            flash("Select a valid payment method.")
            return redirect(url_for("payments"))

        if term not in ("Term 1", "Term 2", "Term 3"):
            flash("Select a valid school term.")
            return redirect(url_for("payments"))

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            # Ensure the student exists before accepting payment.
            cursor.execute(
                "SELECT student_id FROM students WHERE student_id = %s",
                (student_id,)
            )
            student = cursor.fetchone()

            if not student:
                flash("That student ID does not exist. Register the student first.")
                return redirect(url_for("payments"))

            cursor.execute(
                """
                INSERT INTO payments (
                    student_id, amount, payment_date, payment_method,
                    reference_number, term, recorded_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    student_id, amount, valid_date, payment_method,
                    reference_number, term, session["user_id"]
                )
            )

            connection.commit()
            flash("Payment recorded successfully.")

        except Exception:
            app.logger.exception("Payment recording error")
            if connection is not None:
                connection.rollback()
            flash("Unable to record payment. Please try again.")

        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        return redirect(url_for("payments"))

    connection = None
    cursor = None
    payment_list = []
    total_collected = Decimal("0.00")
    payment_count = 0

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT p.payment_id, p.amount, p.payment_date,
                   p.payment_method, p.reference_number, p.term,
                   s.first_name, s.last_name
            FROM payments p
            INNER JOIN students s ON p.student_id = s.student_id
            ORDER BY p.payment_date DESC, p.payment_id DESC
            """
        )
        payment_list = cursor.fetchall()

        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payments"
        )
        total_collected = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM payments")
        payment_count = cursor.fetchone()["total"]

    except Exception:
        app.logger.exception("Payment listing error")
        flash("Unable to load payment records.")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "payments.html",
        payments=payment_list,
        total_collected=total_collected,
        payment_count=payment_count
    )

    
@app.route("/receipt/<int:payment_id>")
def payment_receipt(payment_id):
    # Only logged-in users can view receipts.
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            p.payment_id,
            p.student_id,
            p.amount,
            p.payment_date,
            p.payment_method,
            p.reference_number,
            p.term,
            s.first_name,
            s.last_name,
            s.class_name,
            COALESCE(sf.amount_due, 0) AS amount_due,
            COALESCE((
                SELECT SUM(p2.amount)
                FROM payments p2
                WHERE p2.student_id = p.student_id
                  AND p2.term = p.term
                  AND YEAR(p2.payment_date) = YEAR(p.payment_date)
            ), 0) AS total_paid
        FROM payments p
        JOIN students s ON s.student_id = p.student_id
        LEFT JOIN student_fees sf
            ON sf.student_id = p.student_id
            AND sf.term = p.term
            AND sf.academic_year =
                CAST(YEAR(p.payment_date) AS CHAR)
        WHERE p.payment_id = %s
    """, (payment_id,))

    payment = cursor.fetchone()

    cursor.close()
    conn.close()

    if payment is None:
        return "Payment receipt not found.", 404

    from decimal import Decimal

    amount_due = Decimal(str(payment["amount_due"]))
    total_paid = Decimal(str(payment["total_paid"]))

    payment["outstanding"] = max(
        amount_due - total_paid,
        Decimal("0.00")
    )

    return render_template(
        "receipt.html",
        payment=payment
    )

    
@app.route("/reports", methods=["GET"])
def reports():
    if "user_id" not in session:
        return redirect(url_for("login"))

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    # Validate optional date filters.
    try:
        if start_date:
            date.fromisoformat(start_date)
        if end_date:
            date.fromisoformat(end_date)

        if start_date and end_date and start_date > end_date:
            flash("The start date cannot be after the end date.")
            start_date = ""
            end_date = ""

    except ValueError:
        flash("Please enter valid dates.")
        start_date = ""
        end_date = ""

    connection = None
    cursor = None

    total_students = 0
    total_collected = Decimal("0.00")
    payment_count = 0
    period_total = Decimal("0.00")
    payment_list = []

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Count registered students.
        cursor.execute("SELECT COUNT(*) AS total FROM students")
        total_students = cursor.fetchone()["total"]

        # Calculate all-time collections.
        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payments"
        )
        total_collected = cursor.fetchone()["total"]

        # Count all recorded transactions.
        cursor.execute("SELECT COUNT(*) AS total FROM payments")
        payment_count = cursor.fetchone()["total"]

        # Build the date filter using parameterised SQL.
        conditions = []
        parameters = []

        if start_date:
            conditions.append("p.payment_date >= %s")
            parameters.append(start_date)

        if end_date:
            conditions.append("p.payment_date <= %s")
            parameters.append(end_date)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Retrieve transactions with the corresponding student details.
        cursor.execute(
            f"""
            SELECT
                p.payment_id,
                p.amount,
                p.payment_date,
                p.payment_method,
                p.term,
                s.first_name,
                s.last_name,
                s.class_name
            FROM payments p
            INNER JOIN students s
                ON p.student_id = s.student_id
            {where_clause}
            ORDER BY p.payment_date DESC, p.payment_id DESC
            """,
            tuple(parameters)
        )
        payment_list = cursor.fetchall()

        # Calculate collections for the selected date range.
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(p.amount), 0) AS total
            FROM payments p
            {where_clause}
            """,
            tuple(parameters)
        )
        period_total = cursor.fetchone()["total"]

    except Exception:
        app.logger.exception("Reports page database error")
        flash("Unable to load reports. Please check the database.")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "reports.html",
        total_students=total_students,
        total_collected=total_collected,
        payment_count=payment_count,
        payments=payment_list,
        period_total=period_total,
        start_date=start_date,
        end_date=end_date
    )

    
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if request.method == "POST":
            school_name = request.form.get(
                "school_name", ""
            ).strip()
            school_email = request.form.get(
                "school_email", ""
            ).strip() or None
            school_phone = request.form.get(
                "school_phone", ""
            ).strip() or None
            school_address = request.form.get(
                "school_address", ""
            ).strip() or None

            if not school_name:
                flash("School name is required.")
            else:
                cursor.execute(
                    """
                    UPDATE school_settings
                    SET school_name = %s,
                        school_email = %s,
                        school_phone = %s,
                        school_address = %s
                    WHERE settings_id = 1
                    """,
                    (
                        school_name,
                        school_email,
                        school_phone,
                        school_address
                    )
                )

                # Create the default row if it does not exist.
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        INSERT INTO school_settings (
                            settings_id, school_name, school_email,
                            school_phone, school_address
                        )
                        VALUES (1, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            school_name = %s,
                            school_email = %s,
                            school_phone = %s,
                            school_address = %s
                        """,
                        (
                            school_name, school_email,
                            school_phone, school_address,
                            school_name, school_email,
                            school_phone, school_address
                        )
                    )

                connection.commit()
                flash("School settings saved successfully.")

                return redirect(url_for("settings"))

        cursor.execute(
            """
            SELECT school_name, school_email,
                   school_phone, school_address
            FROM school_settings
            WHERE settings_id = 1
            """
        )
        school = cursor.fetchone()

        if school is None:
            school = {
                "school_name": "Maconte School",
                "school_email": "",
                "school_phone": "",
                "school_address": ""
            }

    except Exception:
        app.logger.exception("Settings page database error")

        if connection is not None:
            connection.rollback()

        flash("Unable to load or save settings. Please check the database.")

        school = {
            "school_name": "Maconte School",
            "school_email": "",
            "school_phone": "",
            "school_address": ""
        }

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "settings.html",
        school_name=school["school_name"],
        school_email=school["school_email"] or "",
        school_phone=school["school_phone"] or "",
        school_address=school["school_address"] or ""
    )

    
@app.route("/outstanding", methods=["GET", "POST"])
def outstanding_fees():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if request.method == "POST":
            student_id = request.form.get("student_id", "").strip()
            term = request.form.get("term", "").strip()
            academic_year = request.form.get("academic_year", "").strip()
            amount_text = request.form.get("amount_due", "").strip()

            if (
                not student_id.isdigit()
                or term not in ("Term 1", "Term 2", "Term 3")
                or len(academic_year) != 4
                or not academic_year.isdigit()
            ):
                flash("Please enter valid student, term and academic year details.")
                return redirect(url_for("outstanding_fees"))

            try:
                amount_due = Decimal(amount_text)
                if not amount_due.is_finite() or amount_due <= 0:
                    raise InvalidOperation
                if amount_due.as_tuple().exponent < -2:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                flash("Enter a valid fee amount greater than zero, with at most two decimal places.")
                return redirect(url_for("outstanding_fees"))

            # Confirm that the student exists.
            cursor.execute(
                "SELECT student_id FROM students WHERE student_id = %s",
                (int(student_id),)
            )

            if cursor.fetchone() is None:
                flash("The selected student does not exist.")
                return redirect(url_for("outstanding_fees"))

            # Add a fee record, or update the existing record
            # for the same student, term and academic year.
            cursor.execute(
                """
                INSERT INTO student_fees
                    (student_id, term, academic_year, amount_due)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    amount_due = %s
                """,
                (
                    int(student_id),
                    term,
                    academic_year,
                    amount_due,
                    amount_due
                )
            )

            connection.commit()
            flash("Expected fees saved successfully.")
            return redirect(url_for("outstanding_fees"))

        # Retrieve students for the registration form.
        cursor.execute(
            """
            SELECT student_id, first_name, last_name, class_name
            FROM students
            ORDER BY first_name, last_name
            """
        )
        students = cursor.fetchall()

        # Calculate paid and outstanding fees for each student,
        # term and academic year.
        cursor.execute(
            """
            SELECT
                sf.student_id,
                s.first_name,
                s.last_name,
                s.class_name,
                sf.term,
                sf.academic_year,
                sf.amount_due,
                COALESCE(p.total_paid, 0) AS total_paid,
                GREATEST(
                    sf.amount_due - COALESCE(p.total_paid, 0),
                    0
                ) AS outstanding
            FROM student_fees sf
            JOIN students s
                ON s.student_id = sf.student_id
            LEFT JOIN (
                SELECT
                    student_id,
                    term,
                    YEAR(payment_date) AS payment_year,
                    SUM(amount) AS total_paid
                FROM payments
                GROUP BY
                    student_id,
                    term,
                    YEAR(payment_date)
            ) p
                ON p.student_id = sf.student_id
                AND p.term = sf.term
                AND p.payment_year = CAST(sf.academic_year AS UNSIGNED)
            ORDER BY
                sf.academic_year DESC,
                sf.term,
                s.first_name,
                s.last_name
            """
        )
        fees = cursor.fetchall()

        total_due = sum(
            (Decimal(str(fee["amount_due"])) for fee in fees),
            Decimal("0.00")
        )

        total_paid = sum(
            (
                min(
                    Decimal(str(fee["total_paid"])),
                    Decimal(str(fee["amount_due"]))
                )
                for fee in fees
            ),
            Decimal("0.00")
        )

        total_outstanding = sum(
            (Decimal(str(fee["outstanding"])) for fee in fees),
            Decimal("0.00")
        )

    except Exception:
        app.logger.exception("Outstanding fees page error")

        if connection is not None:
            connection.rollback()

        flash("Unable to load outstanding fees. Check the database and application terminal.")

        students = []
        fees = []
        total_due = Decimal("0.00")
        total_paid = Decimal("0.00")
        total_outstanding = Decimal("0.00")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "outstanding.html",
        students=students,
        fees=fees,
        total_due=total_due,
        total_paid=total_paid,
        total_outstanding=total_outstanding
    )

    
@app.route("/statement", methods=["GET"])
def student_statement():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    students = []
    selected_student = None
    fee_records = []
    payment_records = []

    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")
    total_outstanding = Decimal("0.00")

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Load all students for the selection list.
        cursor.execute("""
            SELECT student_id, first_name, last_name, class_name
            FROM students
            ORDER BY first_name, last_name
        """)
        students = cursor.fetchall()

        student_id = request.args.get("student_id", "").strip()

        if student_id:
            if not student_id.isdigit():
                flash("Please select a valid student.")
                return redirect(url_for("student_statement"))

            cursor.execute("""
                SELECT student_id, first_name, last_name, class_name
                FROM students
                WHERE student_id = %s
            """, (int(student_id),))

            selected_student = cursor.fetchone()

            if selected_student is None:
                flash("Student not found.")
                return redirect(url_for("student_statement"))

            # Retrieve expected fees and payments for each term.
            cursor.execute("""
                SELECT
                    sf.academic_year,
                    sf.term,
                    sf.amount_due,
                    COALESCE(p.total_paid, 0) AS total_paid,
                    GREATEST(
                        sf.amount_due - COALESCE(p.total_paid, 0),
                        0
                    ) AS outstanding
                FROM student_fees sf
                LEFT JOIN (
                    SELECT
                        student_id,
                        term,
                        YEAR(payment_date) AS payment_year,
                        SUM(amount) AS total_paid
                    FROM payments
                    GROUP BY
                        student_id,
                        term,
                        YEAR(payment_date)
                ) p
                    ON p.student_id = sf.student_id
                    AND p.term = sf.term
                    AND p.payment_year =
                        CAST(sf.academic_year AS UNSIGNED)
                WHERE sf.student_id = %s
                ORDER BY sf.academic_year DESC, sf.term
            """, (int(student_id),))

            fee_records = cursor.fetchall()

            # Retrieve individual payment transactions.
            cursor.execute("""
                SELECT
                    payment_date,
                    term,
                    amount,
                    payment_method,
                    reference_number
                FROM payments
                WHERE student_id = %s
                ORDER BY payment_date DESC, payment_id DESC
            """, (int(student_id),))

            payment_records = cursor.fetchall()

            total_due = sum(
                (Decimal(str(fee["amount_due"])) for fee in fee_records),
                Decimal("0.00")
            )

            total_paid = sum(
                (
                    min(
                        Decimal(str(fee["total_paid"])),
                        Decimal(str(fee["amount_due"]))
                    )
                    for fee in fee_records
                ),
                Decimal("0.00")
            )

            total_outstanding = sum(
                (
                    Decimal(str(fee["outstanding"]))
                    for fee in fee_records
                ),
                Decimal("0.00")
            )

    except Exception:
        app.logger.exception("Student statement page error")

        if connection is not None:
            connection.rollback()

        flash("Unable to load the statement. Check the database and application terminal.")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "statement.html",
        students=students,
        selected_student=selected_student,
        fee_records=fee_records,
        payment_records=payment_records,
        total_due=total_due,
        total_paid=total_paid,
        total_outstanding=total_outstanding
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=False)