import mysql.connector
import time
from datetime import datetime, timedelta


def start_auto_absent():
    while True:
        try:
            # 1. Kumonekta sa Database
            db = mysql.connector.connect(
                host="localhost",
                user="root",
                password="",
                database="face_attendance"
            )
            cursor = db.cursor(dictionary=True)

            now = datetime.now()
            today_date = now.strftime("%Y-%m-%d")
            today_day = now.strftime("%A")
            current_time_str = now.strftime("%H:%M:%S")

            # 2. Kunin lahat ng estudyante na may pasok NGAYONG ARAW gamit ang JOIN
            cursor.execute("""
                SELECT s.id, sch.time_start 
                FROM students s
                JOIN student_schedules sch ON s.id = sch.student_id
                WHERE sch.day = %s
            """, (today_day,))

            scheduled_students = cursor.fetchall()

            # 3. I-check bawat estudyante kung lagpas na sa grace period
            for student in scheduled_students:
                student_id = student['id']
                t_start = student['time_start']

                # MySQL Time conversion
                if isinstance(t_start, str):
                    t_start_obj = datetime.strptime(t_start, "%H:%M:%S").time()
                elif isinstance(t_start, timedelta):
                    t_start_obj = (datetime.min + t_start).time()
                else:
                    t_start_obj = t_start

                start_dt = datetime.combine(now.date(), t_start_obj)

                # 20 minutes grace period bago ma-mark na Absent
                cutoff_dt = start_dt + timedelta(minutes=20)

                # Kung lumagpas na sa cutoff time ang oras ngayon...
                if now >= cutoff_dt:
                    # I-check kung may attendance record na siya for today
                    cursor.execute("SELECT * FROM attendance WHERE student_id=%s AND date=%s", (student_id, today_date))
                    already_marked = cursor.fetchone()

                    if not already_marked:
                        # Kapag wala pa siyang record at lagpas na sa time, mark as Absent
                        cursor.execute("""
                            INSERT INTO attendance (student_id, date, time, status)
                            VALUES (%s, %s, %s, %s)
                        """, (student_id, today_date, current_time_str, "Absent"))
                        db.commit()

            cursor.close()
            db.close()

        except Exception as e:
            print(f"Auto-Absent Error: {e}")

        # Maghihintay ng 60 seconds (1 minute) bago mag-check ulit
        time.sleep(60)


if __name__ == "__main__":
    start_auto_absent()