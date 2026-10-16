import pickle
import cv2
import numpy as np
import os
import face_recognition
import cvzone
import mysql.connector
import subprocess
import sys
import datetime
import time

# 🔥 BAGONG LOGIC: Time-based tracking na may tolerance 🔥
detection_tracker = {}
VERIFICATION_TIME = 3.0  # 3 segundo kailangan nakatingin sa camera (pwede mong baguhin)
TIMEOUT = 2.0  # 2 segundo allowance kapag pumikit o nag-lag (hindi magre-reset agad)

print("Checking encodings...")

need_encode = False

# Check if EncodeFile exists
if not os.path.exists("EncodeFile.p"):
    need_encode = True
else:
    # Load existing encoded IDs
    with open("EncodeFile.p", 'rb') as f:
        encodeListKnown, studentIds = pickle.load(f)

    image_files = os.listdir("Images")

    if len(image_files) != len(studentIds):
        need_encode = True

if need_encode:
    print("Changes detected. Running encoder...")
    subprocess.run([sys.executable, "EncodeGenerator.py"])
    print("Encoding finished.")
else:
    print("No new images detected.")

# database connection
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="face_attendance"
)
cursor = db.cursor(buffered=True)

# camera setup/with changing camera. 0=laptop camera 1=external camera
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(3, 640)
cap.set(4, 480)

# load background image
originalBackground = cv2.imread("Resources/SFICS-ATTENDANCE-SYSTEM.png")

# load mode images
folderModePath = "Resources/Modes"
modePathList = sorted(os.listdir(folderModePath))
imgModeList = [cv2.imread(os.path.join(folderModePath, p)) for p in modePathList]

# load face encodings
file = open("EncodeFile.p", 'rb')
encodeListKnown, studentIds = pickle.load(file)
file.close()

modeType = 0
animationStep = 0
animationStart = 0
currentID = None

studentID = ""
studentName = ""
studentMajor = ""
studentYear = ""
totalAttendance = 0
studentImage = None
time_start = None  # idinagdag ko ito para global sa loop
has_schedule_today = False  # idinagdag ko rin para sa checking

x_offset = 808
y_offset = 44

while True:

    background = originalBackground.copy()

    success, img = cap.read()
    if not success:
        break

    imgS = cv2.resize(img, (0, 0), None, 0.25, 0.25)
    imgS = cv2.cvtColor(imgS, cv2.COLOR_BGR2RGB)

    faceCurFrame = face_recognition.face_locations(imgS)
    encodeCurFrame = face_recognition.face_encodings(imgS, faceCurFrame)

    # 🔥 Kukunin ang current time para sa tracking 🔥
    current_time = time.time()

    # 🔥 Linisin ang tracker kapag matagal na talaga nawala ang tao (lagpas sa 2 seconds timeout) 🔥
    keys_to_delete = []
    for sid, data in detection_tracker.items():
        if current_time - data['last_seen'] > TIMEOUT:
            keys_to_delete.append(sid)
    for sid in keys_to_delete:
        del detection_tracker[sid]

    if len(faceCurFrame) > 1:
        print("⚠️ Multiple faces detected - skipping")
        currentID = "Unknown"
        detection_tracker.clear()
        cv2.putText(background, "PLEASE SCAN ONE BY ONE", (65, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
        continue

    background[162:162 + 480, 55:55 + 640] = img
    background[y_offset:y_offset + 633, x_offset:x_offset + 414] = imgModeList[modeType]

    for faceLoc in faceCurFrame:
        y1, x2, y2, x1 = faceLoc
        y1, x2, y2, x1 = y1 * 4, x2 * 4, y2 * 4, x1 * 4
        bbox = 55 + x1, 162 + y1, x2 - x1, y2 - y1
        cvzone.cornerRect(background, bbox, rt=0)

    # ================= FACE DETECTION =================
    if animationStep == 0 and len(encodeCurFrame) > 0:

        for encodeFace in encodeCurFrame:

            matches = face_recognition.compare_faces(encodeListKnown, encodeFace)
            faceDis = face_recognition.face_distance(encodeListKnown, encodeFace)
            matchIndex = np.argmin(faceDis)

            if matches[matchIndex]:

                tempID = studentIds[matchIndex]

                # 🔥 TIME-BASED VERIFICATION 🔥
                if tempID not in detection_tracker:
                    # Kung first time makita, i-record ang oras
                    detection_tracker[tempID] = {'first_seen': current_time, 'last_seen': current_time}
                    elapsed = 0
                else:
                    # Kung nakita ulit (kahit nag-lag o pumikit basta hindi pa lagpas timeout), i-update ang last_seen
                    detection_tracker[tempID]['last_seen'] = current_time
                    elapsed = current_time - detection_tracker[tempID]['first_seen']

                if elapsed < VERIFICATION_TIME:
                    # Habang hindi pa nakaka-3 seconds, mag-loading screen muna
                    percentage = int((elapsed / VERIFICATION_TIME) * 100)
                    cv2.putText(background, f"Verifying... {percentage}%",
                                (65, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 3)
                    break  # Break sa encodeFace loop para ipakita ang frame, tuloy lang ang while True

                # Kapag umabot na sa VERIFICATION_TIME (100%), ituloy na ang pag-process!
                currentID = tempID
                del detection_tracker[tempID]  # Tanggalin sa tracker para hindi mag-loop

                imagePath = f"Images/{currentID}.png"
                if os.path.exists(imagePath):
                    studentImage = cv2.imread(imagePath)
                    studentImage = cv2.resize(studentImage, (216, 216))
                else:
                    studentImage = None

                # Kunin muna basic info
                cursor.execute("SELECT id, name, course, year_level, total_attendance FROM students WHERE id=%s",
                               (currentID,))
                info = cursor.fetchone()

                if info:
                    studentID = info[0]
                    studentName = info[1]
                    studentMajor = info[2]
                    studentYear = info[3]
                    totalAttendance = info[4]

                    # Kunin ang schedule para lang sa ARAW NGAYON
                    now = datetime.datetime.now()
                    todayDay = now.strftime("%A")

                    cursor.execute("SELECT time_start FROM student_schedules WHERE student_id=%s AND day=%s",
                                   (currentID, todayDay))
                    sched_info = cursor.fetchone()

                    if sched_info:
                        time_start = sched_info[0]
                        has_schedule_today = True
                    else:
                        time_start = None
                        has_schedule_today = False

                else:
                    studentID = currentID
                    studentName = "Unknown"
                    studentMajor = "N/A"
                    studentYear = "-"
                    totalAttendance = 0
                    has_schedule_today = False

                animationStep = 1
                animationStart = time.time()
                break

    # ================= SHOW 2.png =================
    elif animationStep == 1:

        modeType = 1

        if studentImage is not None:
            frame_width = 414
            img_size = 216
            center_x = x_offset + (frame_width - img_size) // 2
            center_y = y_offset + 130

            background[
                center_y: center_y + img_size,
                center_x: center_x + img_size
            ] = studentImage

        (w, h), _ = cv2.getTextSize(
            studentName,
            cv2.FONT_HERSHEY_COMPLEX,
            0.8,
            2
        )
        offset = (414 - w) // 2

        cv2.putText(background, studentName,
                    (808 + offset, 445),
                    cv2.FONT_HERSHEY_COMPLEX,
                    0.8, (60, 60, 60), 2)

        cv2.putText(background, studentID,
                    (1006, 493),
                    cv2.FONT_HERSHEY_COMPLEX,
                    0.6, (120, 120, 120), 2)

        cv2.putText(background, studentMajor,
                    (1006, 550),
                    cv2.FONT_HERSHEY_COMPLEX,
                    0.6, (120, 120, 120), 2)

        cv2.putText(background, str(totalAttendance),
                    (860, 125),
                    cv2.FONT_HERSHEY_COMPLEX,
                    1, (255, 255, 255), 2)

        if time.time() - animationStart > 3:

            now = datetime.datetime.now()
            dateString = now.strftime("%Y-%m-%d")
            timeString = now.strftime("%H:%M:%S")

            cursor.execute(
                "SELECT * FROM attendance WHERE student_id=%s AND date=%s",
                (currentID, dateString)
            )
            alreadyMarked = cursor.fetchone()

            if alreadyMarked:
                # Walang babaguhin dito.
                db.commit()
                animationStep = 3

            else:

                current_time_log = now.time()

                # ================= LOGIC =================
                if not has_schedule_today:
                    status = "No Schedule Today"
                    cursor.execute(
                        "INSERT INTO attendance (student_id, date, time, status) VALUES (%s,%s,%s,%s)",
                        (currentID, dateString, timeString, status)
                    )
                    db.commit()
                    animationStep = 3

                else:
                    # Kung may pasok
                    if isinstance(time_start, str):
                        time_start = datetime.datetime.strptime(time_start, "%H:%M:%S").time()
                    elif isinstance(time_start, datetime.timedelta):
                        time_start = (datetime.datetime.min + time_start).time()

                    # convert to datetime
                    start_datetime = datetime.datetime.combine(datetime.date.today(), time_start)
                    current_datetime = datetime.datetime.combine(datetime.date.today(), current_time_log)

                    # 20 mins grace
                    cutoff_time = start_datetime + datetime.timedelta(minutes=20)

                    # LOGIC
                    if current_datetime <= start_datetime:
                        status = "Present"
                    elif start_datetime < current_datetime <= cutoff_time:
                        status = "Late"
                    else:
                        status = "Absent"

                    cursor.execute(
                        "INSERT INTO attendance (student_id, date, time, status) VALUES (%s,%s,%s,%s)",
                        (currentID, dateString, timeString, status)
                    )

                    db.commit()
                animationStep = 2
                animationStart = time.time()

    elif animationStep == 2:

        modeType = 2

        if time.time() - animationStart > 2:
            animationStep = 0
            modeType = 0
            currentID = None
            studentImage = None
            studentID = ""
            studentName = ""
            studentMajor = ""
            totalAttendance = 0
            detection_tracker.clear()  # Siguraduhing malinis ang tracker

    elif animationStep == 3:

        modeType = 3
        # I-reset din after a few seconds para hindi ma-stuck sa "Already Marked"
        if time.time() - animationStart > 2:
            animationStep = 0
            modeType = 0
            currentID = None
            detection_tracker.clear()  # Siguraduhing malinis ang tracker

    cv2.imshow("SFICS ATTENDANCE", background)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()