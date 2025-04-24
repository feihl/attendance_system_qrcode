from flask import (
    Flask, render_template, request, redirect, url_for, 
    flash, send_from_directory, session, Response, jsonify, send_file
)
from werkzeug.utils import secure_filename

import sqlite3
import os
import qrcode
import requests
import numpy as np
import io
import csv
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from dateutil import parser
# import cv2  # Uncomment if needed
from pyzbar.pyzbar import decode
from io import BytesIO



app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists('database'):
    os.makedirs('database')
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists('static/qrcodes'):
    os.makedirs('static/qrcodes')

def get_db_connection():
    conn = sqlite3.connect('database/database.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

conn = get_db_connection()
c = conn.cursor()

# Create students_tbl
c.execute('''CREATE TABLE IF NOT EXISTS students_tbl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lastname TEXT NOT NULL,
    firstname TEXT NOT NULL,
    middlename TEXT,
    usn TEXT UNIQUE NOT NULL,
    course TEXT NOT NULL,
    year TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    password TEXT NOT NULL,
    profile_picture TEXT,
    approved_by INTEGER,
    FOREIGN KEY (approved_by) REFERENCES admin_tbl(id)
)''')

# Create admin_tbl
c.execute('''CREATE TABLE IF NOT EXISTS admin_tbl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lastname TEXT NOT NULL,
    firstname TEXT NOT NULL,
    middlename TEXT,
    password TEXT NOT NULL
)''')

# Create event_type_tbl
c.execute('''CREATE TABLE IF NOT EXISTS event_type_tbl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    date_created TEXT NOT NULL,
    created_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES admin_tbl(id)
)''')

# Create activity_tbl
c.execute('''CREATE TABLE IF NOT EXISTS activity_tbl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type INTEGER NOT NULL,
    activity_name TEXT NOT NULL,
    start_datetime TEXT NOT NULL,
    end_datetime TEXT NOT NULL,
    created_by INTEGER,
    FOREIGN KEY (event_type) REFERENCES event_type_tbl(id),
    FOREIGN KEY (created_by) REFERENCES admin_tbl(id)
)''')

# Create attendance_list_tbl
c.execute('''CREATE TABLE IF NOT EXISTS attendance_list_tbl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_usn TEXT NOT NULL,
    event_type INTEGER NOT NULL,
    activity_id INTEGER NOT NULL,
    time_in_date_and_time TEXT NOT NULL,
    time_in_status TEXT NOT NULL,
    time_out_date_and_time TEXT NOT NULL,
    time_out_status TEXT NOT NULL,
    FOREIGN KEY (student_usn) REFERENCES students_tbl(usn),
    FOREIGN KEY (event_type) REFERENCES event_type_tbl(id),
    FOREIGN KEY (activity_id) REFERENCES activity_tbl(id)
)''')


conn.commit()
conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def generate_qr_code(usn):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(usn)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    img.save(f'static/qrcodes/{usn}.png')


@app.route('/admin')
def admin_index():
    print("Session Data:", session)

    if 'admin_id' in session and session['admin_id']:
        return redirect(url_for('admin_dashboard'))
    
    return render_template('admin.html')


@app.route('/admin/register', methods=['GET', 'POST'])
def admin_register():
    if request.method == 'POST':
        lastname = request.form['lastname']
        firstname = request.form['firstname']
        middlename = request.form['middlename']
        password = request.form['password']

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO admin_tbl (lastname, firstname, middlename, password) VALUES (?, ?, ?, ?)",
                         (lastname, firstname, middlename, password))
            conn.commit()
            flash('Admin registration successful!', 'success')
        except sqlite3.IntegrityError:
            flash('An error occurred. Please try again.', 'error')
        finally:
            conn.close()

        return redirect(url_for('admin_login'))

    return render_template('admin_register.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        firstname = request.form['firstname']
        password = request.form['password']

        conn = get_db_connection()
        admin = conn.execute("SELECT * FROM admin_tbl WHERE firstname = ? AND password = ?",
                             (firstname, password)).fetchone()
        conn.close()

        if admin:
            session['admin_id'] = admin['id']
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid firstname or password!', 'error')

    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    flash('You have been logged out!', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        flash('You need to log in to access this page!', 'error')
        return redirect(url_for('admin_login'))

    conn = get_db_connection()

    activities = conn.execute('''
        SELECT 
            a.id AS "Activity ID",
            e.event_name AS "Event Name",
            a.activity_name AS "Activity Name",
            e.event_type AS "Event Type",
            a.start_datetime AS "Start Date",
            a.end_datetime AS "End Date"
        FROM 
            activity_tbl a
        JOIN 
            event_type_tbl e ON a.event_type = e.id
    ''').fetchall()

    students = conn.execute("SELECT * FROM students_tbl").fetchall()

    conn.close()

    return render_template('admin_dashboard.html', activities=activities, students=students)

@app.route('/admin/add_activity', methods=['POST'])
def add_activity():
    if 'admin_id' not in session:
        flash('You need to log in to access this page!', 'error')
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        event_name = request.form['eventName']
        event_type = request.form['eventType']
        activity_names = request.form.getlist('activityName[]')
        start_datetimes = request.form.getlist('startDatetime[]')
        end_datetimes = request.form.getlist('endDatetime[]')

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO event_type_tbl (event_name, event_type, date_created, created_by) VALUES (?, ?, datetime('now'), ?)",
                         (event_name, event_type, session['admin_id']))
            event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for name, start, end in zip(activity_names, start_datetimes, end_datetimes):
                conn.execute("INSERT INTO activity_tbl (event_type, activity_name, start_datetime, end_datetime, created_by) VALUES (?, ?, ?, ?, ?)",
                             (event_id, name, start, end, session['admin_id']))

            conn.commit()
            flash('Activity added successfully!', 'success')
        except sqlite3.IntegrityError:
            flash('An error occurred. Please try again.', 'error')
        finally:
            conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/edit_activity/event-<int:event_id>/activity-<int:activity_id>', methods=['GET'])
def edit_activity(event_id, activity_id):
    if 'admin_id' not in session:
        flash('You need to log in to access this page!', 'error')
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    try:
        # Get the event information
        event = conn.execute("SELECT * FROM event_type_tbl WHERE id = ?", (event_id,)).fetchone()
        
        # Get the activity information
        activity = conn.execute(
            "SELECT * FROM activity_tbl WHERE id = ? AND event_type = ?", 
            (activity_id, event_id)
        ).fetchone()
    finally:
        conn.close()

    if not event or not activity:
        flash('Event or activity not found!', 'error')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('edit_activity.html', event=event, activity=activity)

@app.route('/update_activity/event-<int:event_id>/activity-<int:activity_id>', methods=['POST'])
def update_activity(event_id, activity_id):
    if 'admin_id' not in session:
        flash('You need to log in to access this page!', 'error')
        return redirect(url_for('admin_login'))
    
    activity_name = request.form['activity_name']
    start_date = request.form.get('start_date', '')
    start_time = request.form.get('start_time', '')
    end_date = request.form.get('end_date', '')
    end_time = request.form.get('end_time', '')

    # Combine date and time for storage
    start_datetime = f"{start_date} {start_time}" if start_date and start_time else None
    end_datetime = f"{end_date} {end_time}" if end_date and end_time else None

    conn = get_db_connection()
    try:
        conn.execute("""
            UPDATE activity_tbl 
            SET activity_name = ?, start_datetime = ?, end_datetime = ?
            WHERE id = ? AND event_type = ?
        """, (activity_name, start_datetime, end_datetime, activity_id, event_id))
        conn.commit()
        flash('Activity updated successfully!', 'success')
    except sqlite3.Error as e:
        flash(f'An error occurred: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('view_event', event_id=event_id))

@app.route('/delete_activity/event-<int:event_id>/activity-<int:activity_id>', methods=['POST'])
def delete_activity(event_id, activity_id):
    if 'admin_id' not in session:
        flash('You need to log in to access this page!', 'error')
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    try:
        # Fetch the correct event_type if event_id refers to event_tbl
        cursor = conn.execute("SELECT event_type FROM event_tbl WHERE id = ?", (event_id,))
        event_type = cursor.fetchone()

        if event_type:
            conn.execute("DELETE FROM activity_tbl WHERE id = ? AND event_type = ?", (activity_id, event_type[0]))
            conn.commit()
            flash('Activity deleted successfully!', 'success')
        else:
            flash('Invalid event ID!', 'error')

    except sqlite3.Error as e:  
        flash(f'An error occurred: {str(e)}', 'error')

    finally:
        conn.close()

    return redirect(url_for('view_event', event_id=event_id))







@app.route('/')
def index():
    if 'usn' in session:
        return redirect(url_for('profile', usn=session['usn']))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        lastname = request.form['lastname']
        firstname = request.form['firstname']
        middlename = request.form['middlename']
        usn = request.form['usn']
        course = request.form['course']
        year = request.form['year']
        dob = request.form['dob']
        password = request.form['password']
        profile_picture = request.files['profile_picture']

        # First check if USN already exists before handling file upload
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM students_tbl WHERE usn = ?", (usn,))
        existing_user = c.fetchone()
        
        if existing_user:
            conn.close()
            flash('USN already exists! Please use a different USN.', 'danger')
            # Return to the registration form with previously entered data
            return render_template('register.html', 
                                  lastname=lastname,
                                  firstname=firstname,
                                  middlename=middlename,
                                  usn=usn,
                                  course=course,
                                  year=year,
                                  dob=dob)
        
        # Handle file upload only if USN is unique
        if profile_picture and allowed_file(profile_picture.filename):
            filename = secure_filename(profile_picture.filename)
            profile_picture.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = None

        try:
            c.execute("INSERT INTO students_tbl (lastname, firstname, middlename, usn, course, year, date_of_birth, password, profile_picture) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (lastname, firstname, middlename, usn, course, year, dob, password, filename))
            conn.commit()
            generate_qr_code(usn)
            flash('Registration successful!', 'success')
            conn.close()
            return redirect(url_for('index'))
        except Exception as e:
            conn.close()
            flash(f'An error occurred during registration: {str(e)}', 'danger')
            return render_template('register.html',
                                  lastname=lastname,
                                  firstname=firstname,
                                  middlename=middlename,
                                  usn=usn,
                                  course=course,
                                  year=year,
                                  dob=dob)

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usn = request.form['usn']
        password = request.form['password']

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM students_tbl WHERE usn = ? AND password = ?", (usn, password))
        user = c.fetchone()
        conn.close()

        if user:
            session['usn'] = usn
            return redirect(url_for('profile', usn=usn))
        else:
            flash('Invalid USN or password!', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usn', None)
    flash('You have been logged out!', 'success')
    return redirect(url_for('index'))

@app.route('/profile/<usn>')
def profile(usn):
    if 'usn' not in session or session['usn'] != usn:
        flash('You need to log in to access this page!', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM students_tbl WHERE usn = ?", (usn,))
    user = c.fetchone()
    conn.close()

    if user:
        return render_template('profile.html', user=user)
    else:
        flash('User not found!', 'error')
        return redirect(url_for('index'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/multithreads')
def multithreads_page():
    conn = get_db_connection()

    multithreads_data = conn.execute("SELECT * FROM event_type_tbl WHERE event_type = 'Multithreads'")

    return render_template('multithreads.html', threads=multithreads_data)


@app.route('/Singlethreads')
def singlethreads_page():
    conn = get_db_connection()

    singlethreads_data = conn.execute("SELECT * FROM event_type_tbl WHERE event_type = 'Singlethreads'")

    return render_template('Singlethreads.html', threads=singlethreads_data)


@app.route('/qrcode/<usn>')
def view_qrcode(usn):
    qr_path = f'static/qrcodes/{usn}.png'
    if os.path.exists(qr_path):
        return send_from_directory('static/qrcodes', f'{usn}.png')
    else:
        flash('QR Code not found!', 'error')
        return redirect(url_for('admin'))
    
@app.route('/events/<event_id>')
def view_event(event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM event_type_tbl WHERE id = ?", (event_id,))
    event = c.fetchone()
    c.execute("SELECT * FROM activity_tbl WHERE event_type = ?", (event_id,))
    activities = c.fetchall()
    conn.close()

    return render_template('event.html', event=event, activities=activities)

@app.route('/view_students/event-<int:event_id>/activity-<int:activity_id>', methods=['GET', 'POST'])
def view_students(event_id, activity_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Get activity and event info
    c.execute(
        """
        SELECT a.activity_name, e.event_name 
        FROM activity_tbl a 
        JOIN event_type_tbl e ON a.event_type = e.id 
        WHERE a.id = ? AND e.id = ?
        """, 
        (activity_id, event_id)
    )
    result = c.fetchone()

    if not result:
        return jsonify({"error": "Event and Activity not found"}), 404

    activity = {"id": activity_id, "activity_name": result[0]}
    event = {"id": event_id, "event_name": result[1]}

    # Initialize filter variables
    filter_type = ""
    filter_value = ""
    
    # Handle filter form (if POST)
    if request.method == 'POST':
        filter_type = request.form.get('filter_type', '')
        filter_value = request.form.get('filter_value', '')

    # Build the base query
    query = """
    SELECT 
        students_tbl.usn,
        students_tbl.firstname || ' ' || students_tbl.middlename || ' ' || students_tbl.lastname AS student_name,
        event_type_tbl.event_name,
        activity_tbl.activity_name,
        attendance_list_tbl.time_in_date_and_time,
        attendance_list_tbl.time_in_status,
        attendance_list_tbl.time_out_date_and_time,
        attendance_list_tbl.time_out_status
    FROM attendance_list_tbl
    JOIN students_tbl ON attendance_list_tbl.student_usn = students_tbl.usn
    JOIN activity_tbl ON attendance_list_tbl.activity_id = activity_tbl.id
    JOIN event_type_tbl ON attendance_list_tbl.event_type = event_type_tbl.id
    WHERE attendance_list_tbl.event_type = ? AND attendance_list_tbl.activity_id = ?
    """
    params = [event_id, activity_id]

    # Apply filter if both type and value are provided
    if filter_type and filter_value:
        if filter_type == 'year':
            query += " AND students_tbl.year = ?"
            params.append(filter_value)
        elif filter_type == 'course':
            query += " AND students_tbl.course LIKE ?"
            params.append(f"%{filter_value}%")  # Partial match for course

    # Execute query
    c.execute(query, params)
    students = c.fetchall()
    conn.close()

    # Render template with data
    return render_template(
        'students_attendance.html', 
        event=event, 
        students=students, 
        activity=activity,
        filter_type=filter_type,
        filter_value=filter_value
    )






@app.route('/attendance/event-<int:event_id>/activity-<int:activity_id>', methods=['GET'])
def attendance(event_id, activity_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT a.activity_name, e.event_name FROM activity_tbl a "
            "JOIN event_type_tbl e ON a.event_type = e.id "
            "WHERE a.id = ? AND e.id = ?", 
            (activity_id, event_id)
        )
        result = c.fetchone()

    if not result:
        return "Invalid event or activity.", 404

    activity = {"id": activity_id, "activity_name": result[0]}
    event = {"id": event_id, "event_name": result[1]}

    return render_template('attendance.html', activity=activity, event=event)


@app.route('/verify_student', methods=['POST'])
def verify_student():
    usn = request.form.get("usn")

    if not usn:
        return jsonify({"error": "Missing student USN"}), 400

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM students_tbl WHERE usn = ?", (usn,))
        student_details = c.fetchone()

    if student_details is None:
        return jsonify({"error": "Student not found"}), 404

    if student_details[9]:
        profile_picture = url_for('static', filename=f'uploads/{student_details[9]}')
    else:
        profile_picture = url_for('static', filename='uploads/default_profile.jpg')

    return jsonify({
        "student": {
            "fullname": f"{student_details[1]} {student_details[2]} {student_details[3]}",
            "course": student_details[5],
            "year": student_details[6],
            "usn": student_details[4],
            "profile_picture": profile_picture
        }
    })

@app.route('/submit_scan/<int:event_id>', methods=['POST'])
def submit_scan(event_id):
    usn = request.form.get("usn")
    activity_id = request.form.get("activity_id")

    if not usn or not activity_id:
        return jsonify({"error": "Missing data"}), 400

    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT start_datetime FROM activity_tbl WHERE id = ?", (activity_id,))
        activity = c.fetchone()

    if not activity:
        return jsonify({"error": "Activity not found"}), 404

    start_time = parser.parse(activity["start_datetime"])  
    time_in = datetime.now()

    time_diff = (time_in - start_time).total_seconds() / 60
    if time_diff <= 0:
        time_in_status = "On Time"
    elif time_diff <= 15:
        time_in_status = "15 mins late"
    elif time_diff <= 30:
        time_in_status = "30 mins late"
    else:
        time_in_status = "LATE"

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''SELECT * FROM attendance_list_tbl 
                     WHERE student_usn = ? AND activity_id = ? AND event_type = ? 
                     AND time_out_status = "Not Checked Out"''', 
                  (usn, activity_id, event_id))
        existing_record = c.fetchone()

    if existing_record:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute('''UPDATE attendance_list_tbl 
                         SET time_in_date_and_time = ?, time_in_status = ? 
                         WHERE student_usn = ? AND activity_id = ? AND event_type = ? 
                         AND time_out_status = "Not Checked Out"''', 
                      (current_timestamp, time_in_status, usn, activity_id, event_id))
            conn.commit()

        return jsonify({"message": "Attendance updated!", "time_in_status": time_in_status})

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO attendance_list_tbl (
            student_usn, 
            event_type, 
            activity_id, 
            time_in_date_and_time, 
            time_in_status, 
            time_out_date_and_time, 
            time_out_status
        ) VALUES (?, ?, ?, ?, ?, "Not Checked Out", "Not Checked Out")''', 
        (usn, event_id, activity_id, current_timestamp, time_in_status))
        conn.commit()

    return jsonify({"message": "Attendance recorded!", "time_in_status": time_in_status})

    
@app.route('/timeout/event-<int:event_id>/activity-<int:activity_id>', methods=['GET'])
def timeout_attendance(event_id, activity_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT a.activity_name, e.event_name FROM activity_tbl a "
            "JOIN event_type_tbl e ON a.event_type = e.id "
            "WHERE a.id = ? AND e.id = ?", 
            (activity_id, event_id)
        )
        result = c.fetchone()

    if not result:
        return "Invalid event or activity.", 404

    activity = {"id": activity_id, "activity_name": result[0]}
    event = {"id": event_id, "event_name": result[1]}

    return render_template('timeout_attendance.html', activity=activity, event=event)


@app.route('/timeout_submit_scan/<int:event_id>', methods=['POST'])
def timeout_submit_scan(event_id):
    usn = request.form.get("usn")
    activity_id = request.form.get("activity_id")
    time_out_status = request.form.get("time_out_status", "Checked Out")

    if not usn or not activity_id:
        return jsonify({"error": "Missing data"}), 400

    from datetime import datetime
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''SELECT * FROM attendance_list_tbl 
                     WHERE student_usn = ? AND activity_id = ? AND event_type = ?''', 
                  (usn, activity_id, event_id))
        existing_record = c.fetchone()

    if existing_record:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute('''UPDATE attendance_list_tbl 
                         SET time_out_date_and_time = ?, time_out_status = ? 
                         WHERE student_usn = ? AND activity_id = ? AND event_type = ?''', 
                      (current_timestamp, time_out_status, usn, activity_id, event_id))
            conn.commit()
        return jsonify({"message": "Time-out updated!"})

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO attendance_list_tbl (
            student_usn,    
            event_type, 
            activity_id, 
            time_out_date_and_time, 
            time_out_status
        ) VALUES (?, ?, ?, ?, ?)''', 
        (usn, event_id, activity_id, current_timestamp, time_out_status))

        conn.commit()

    return jsonify({"message": "Time-out recorded as a new entry!"})

def insert_student(data):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO students_tbl (
                lastname, firstname, middlename, usn, course, year,
                date_of_birth, password, profile_picture, approved_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', data)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# Generate QR code if it doesn't already exist
def generate_qr_code(usn):
    folder = 'static/qrcodes'
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f'{usn}.png')
    
    if not os.path.exists(filepath):
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(usn)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white').convert('RGB')
        
        # Prepare to draw text
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()
        
        draw = ImageDraw.Draw(img)
        
        # Get text size using textbbox (compatible with Pillow 8+)
        bbox = draw.textbbox((0, 0), usn, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        img_width, img_height = img.size
        new_height = img_height + text_height + 10
        
        # Create new image with extra space
        new_img = Image.new("RGB", (img_width, new_height), "white")
        new_img.paste(img, (0, 0))
        
        # Draw USN text centered
        draw = ImageDraw.Draw(new_img)
        text_position = ((img_width - text_width) // 2, img_height + 5)
        draw.text(text_position, usn, font=font, fill="black")
        
        new_img.save(filepath)
        print(f"QR code with USN generated for {usn}")
    
    return filepath

# Upload CSV route
@app.route('/upload-students', methods=['POST'])
def upload_students():
    if 'file' not in request.files:
        return jsonify({'error': 'CSV file is required'}), 400

    file = request.files['file']

    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files are allowed'}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
    csv_reader = csv.DictReader(stream)

    inserted = 0
    skipped = 0
    qrcodes = []

    for row in csv_reader:
        try:
            usn = row['USN'].strip()
            lastname = row['LAST NAME'].strip()
            firstname = row['FIRST NAME'].strip()
            middlename = row['MIDDLE NAME'].strip()
            program = row['PROGRAM'].strip()
            year = row['YEAR'].strip()

            password = usn[:4] + firstname.replace(" ", "").lower()
            date_of_birth = "no data recorded"
            profile_picture = "default_profile.jpg"
            approved_by = None

            student_data = (
                lastname, firstname, middlename, usn, program, year,
                date_of_birth, password, profile_picture, approved_by
            )

            if insert_student(student_data):
                qr_path = generate_qr_code(usn)
                qrcodes.append(qr_path)
                inserted += 1
            else:
                skipped += 1
        except KeyError as e:
            return jsonify({'error': f'Missing expected column: {e}'}), 400

    return jsonify({
        'status': 'Upload complete',
        'inserted': inserted,
        'skipped (possibly duplicates)': skipped,
        'qrcodes_generated': qrcodes
    })


@app.route('/download_excel/<int:event_type_id>/<int:activity_id>')
def download_excel(event_type_id, activity_id):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row  # Enable dictionary-like row access
    cursor = conn.cursor()

    # SQL query with necessary fields
    cursor.execute("""
        SELECT 
            attendance_list_tbl.id,
            students_tbl.usn AS student_usn,
            students_tbl.firstname || ' ' || students_tbl.middlename || ' ' || students_tbl.lastname AS student_name,
            event_type_tbl.event_name,
            activity_tbl.activity_name,
            attendance_list_tbl.time_in_date_and_time,
            attendance_list_tbl.time_in_status,
            attendance_list_tbl.time_out_date_and_time,
            attendance_list_tbl.time_out_status
        FROM attendance_list_tbl
        JOIN students_tbl ON attendance_list_tbl.student_usn = students_tbl.usn
        JOIN activity_tbl ON attendance_list_tbl.activity_id = activity_tbl.id
        JOIN event_type_tbl ON attendance_list_tbl.event_type = event_type_tbl.id
        WHERE attendance_list_tbl.event_type = ? AND attendance_list_tbl.activity_id = ?
    """, (event_type_id, activity_id))

    rows = cursor.fetchall()
    conn.close()

    # Convert results into dictionaries for DataFrame
    students = [{
        'Student USN': row['student_usn'],
        'Student Name': row['student_name'],
        'Event Type': row['event_name'],
        'Activity Name': row['activity_name'],
        'Time In': row['time_in_date_and_time'],
        'Status (In)': row['time_in_status'],
        'Time Out': row['time_out_date_and_time'],
        'Status (Out)': row['time_out_status']
    } for row in rows]

    # Create Excel file in memory
    df = pd.DataFrame(students)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Attendance')

    output.seek(0)
    return send_file(output, download_name=f'attendance_{event_type_id}_{activity_id}.xlsx', as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)