from flask import Flask, render_template, jsonify, request, redirect, url_for, session
import mysql.connector
from datetime import datetime, timedelta
import subprocess
import sys
import os
import signal
import base64
import face_recognition
import numpy as np
import cv2
import threading
import auto_absent

camera_process = None

app = Flask(__name__)
app.secret_key = "sfics_secret_key"
app.config["SESSION_PERMANENT"] = False


def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="face_attendance"
    )


def get_all_students():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students")
    students = cursor.fetchall()
    cursor.close()
    db.close()
    return students


@app.route("/")
def dashboard():
    if "admin" not in session:
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route('/api/attendance')
def api_attendance():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    selected_date = request.args.get("date")

    if not selected_date:
        selected_date = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT attendance.student_id,
               students.name,
               students.course,
               attendance.date,
               attendance.time,
               attendance.status
        FROM attendance
        JOIN students ON attendance.student_id = students.id
        WHERE attendance.date = %s
        ORDER BY attendance.time DESC
    """, (selected_date,))

    records = cursor.fetchall()
    for record in records:
        record["date"] = str(record["date"])
        record["time"] = str(record["time"])

    cursor.close()
    db.close()
    return jsonify(records)


@app.route("/students")
def students():
    if "admin" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students")
    students = cursor.fetchall()
    total_students = len(students)

    cursor.close()
    db.close()

    return render_template("students.html", students=students, total_students=total_students)


@app.route("/reports")
def reports():
    if "admin" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    selected_date = request.args.get("date")

    if selected_date:
        cursor.execute("""
            SELECT attendance.student_id, students.name, students.course,
                   attendance.date, attendance.time, attendance.status
            FROM attendance
            JOIN students ON attendance.student_id = students.id
            WHERE attendance.date = %s
            ORDER BY attendance.time DESC
        """, (selected_date,))
    else:
        cursor.execute("""
            SELECT attendance.student_id, students.name, students.course,
                   attendance.date, attendance.time, attendance.status
            FROM attendance
            JOIN students ON attendance.student_id = students.id
            ORDER BY attendance.date DESC, attendance.time DESC
        """)

    records = cursor.fetchall()
    total = len(records)
    present = len([r for r in records if r["status"] == "Present"])
    late = len([r for r in records if r["status"] == "Late"])
    absent = len([r for r in records if r["status"] == "Absent"])

    cursor.close()
    db.close()
    return render_template("reports.html", records=records, total=total, present=present, late=late, absent=absent)


@app.route("/settings")
def settings():
    if "admin" not in session:
        return redirect(url_for("login"))
    return render_template("settings.html")


@app.route("/add_student", methods=["POST"])
def add_student():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    student_id = request.form["student_id"]
    name = request.form["name"]
    gender = request.form.get("gender")
    address = request.form.get("address")
    course = request.form["course"]
    year_level = request.form["year_level"]

    # 🔍 CHECK IF ID EXISTS
    cursor.execute("SELECT * FROM students WHERE id=%s", (student_id,))
    if cursor.fetchone():
        cursor.close()
        db.close()
        return render_template("students.html", students=get_all_students(), error="Student ID already exists!")

    # ✅ INSERT SA STUDENTS TABLE
    cursor.execute("""
        INSERT INTO students (id, name, gender, address, course, year_level, total_attendance)
        VALUES (%s, %s, %s, %s, %s, %s, 0)
    """, (student_id, name, gender, address, course, year_level))

    # ✅ DYNAMIC SCHEDULE INSERTION
    days_checked = request.form.getlist("schedule_days")
    for day in days_checked:
        t_start = request.form.get(f"time_start_{day}")
        t_end = request.form.get(f"time_end_{day}")

        if t_start and t_end:
            cursor.execute("""
                INSERT INTO student_schedules (student_id, day, time_start, time_end)
                VALUES (%s, %s, %s, %s)
            """, (student_id, day, t_start, t_end))

    db.commit()
    cursor.close()
    db.close()
    return redirect(url_for("students"))


@app.route("/delete_student/<student_id>")
def delete_student(student_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("DELETE FROM attendance WHERE student_id=%s", (student_id,))
    cursor.execute("DELETE FROM student_schedules WHERE student_id=%s", (student_id,))
    cursor.execute("DELETE FROM students WHERE id=%s", (student_id,))

    image_path = f"Images/{student_id}.png"
    if os.path.exists(image_path):
        os.remove(image_path)

    db.commit()
    cursor.close()
    db.close()
    return redirect(url_for("students"))


@app.route("/save_face", methods=["POST"])
def save_face():
    data = request.get_json()
    student_id = data["student_id"]
    image_data = data["image"]
    overwrite = data.get("overwrite", False)

    os.makedirs("Images", exist_ok=True)
    file_path = f"Images/{student_id}.png"

    if os.path.exists(file_path) and not overwrite:
        return jsonify({"exists": True, "message": "⚠️ This student already has a face registered."})

    image_data = image_data.split(",")[1]
    image_bytes = base64.b64decode(image_data)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    cv2.imwrite(file_path, img)

    subprocess.run([sys.executable, "EncodeGenerator.py"])

    return jsonify({"exists": False, "message": "✅ Face saved successfully!"})


@app.route("/edit_student/<student_id>", methods=["POST"])
def edit_student(student_id):
    db = get_db()
    cursor = db.cursor()

    name = request.form["name"]
    gender = request.form.get("gender")
    address = request.form.get("address")
    course = request.form["course"]
    year_level = request.form["year_level"]

    cursor.execute("""
        UPDATE students
        SET name=%s, gender=%s, address=%s, course=%s, year_level=%s
        WHERE id=%s
    """, (name, gender, address, course, year_level, student_id))

    db.commit()
    cursor.close()
    db.close()
    return redirect(url_for("students"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "login_attempts" not in session:
        session["login_attempts"] = 0

    if "lock_time" in session:
        lock_time = datetime.fromisoformat(session["lock_time"])
        if datetime.now() < lock_time:
            remaining = lock_time - datetime.now()
            minutes = int(remaining.total_seconds() // 60)
            return render_template("login.html", error=f"Account locked. Try again in {minutes} minutes.")
        else:
            session.pop("lock_time")
            session["login_attempts"] = 0

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == "admin" and password == "sfics123":
            session["admin"] = True
            session["username"] = username
            session["login_attempts"] = 0
            return redirect(url_for("dashboard"))
        else:
            session["login_attempts"] += 1
            if session["login_attempts"] >= 3:
                lock_until = datetime.now() + timedelta(hours=1)
                session["lock_time"] = lock_until.isoformat()
                return render_template("login.html", error="Too many failed attempts. Locked for 1 hour.")
            return render_template("login.html",
                                   error=f"Invalid credentials. Attempts left: {3 - session['login_attempts']}")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/start_facial")
def start_facial():
    global camera_process
    if camera_process is None:
        camera_process = subprocess.Popen([sys.executable, "main.py"])
    return redirect(url_for("dashboard"))


@app.route("/stop_facial")
def stop_facial():
    global camera_process
    if camera_process:
        camera_process.terminate()
        camera_process = None
    return redirect(url_for("dashboard"))


@app.route("/detect_face", methods=["POST"])
def detect_face():
    data = request.get_json()
    image_data = data["image"].split(",")[1]
    img_bytes = base64.b64decode(image_data)
    np_arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)

    return jsonify({"face_detected": len(faces) > 0})


@app.route("/upload_face", methods=["POST"])
def upload_face():
    student_id = request.form["student_id"]
    file = request.files["face"]
    overwrite = request.form.get("overwrite", "false") == "true"

    if file.filename == "":
        return jsonify({"message": "No file selected"})

    os.makedirs("Images", exist_ok=True)
    file_path = f"Images/{student_id}.png"

    if os.path.exists(file_path) and not overwrite:
        return jsonify({"exists": True, "message": "⚠️ This student already has a registered face."})

    file.save(file_path)
    subprocess.run([sys.executable, "EncodeGenerator.py"])

    return jsonify({"exists": False, "message": "Face saved successfully!"})


@app.route("/check_existing_face/<student_id>")
def check_existing_face(student_id):
    file_path = f"Images/{student_id}.png"
    return jsonify({"exists": os.path.exists(file_path),
                    "message": "This student already has a registered face." if os.path.exists(file_path) else ""})


if __name__ == "__main__":
    threading.Thread(target=auto_absent.start_auto_absent, daemon=True).start()
    app.run(debug=True)