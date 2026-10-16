import cv2
import face_recognition
import os
import pickle

folderPath = 'Images'
pathList = os.listdir(folderPath)

imgList = []
studentIds = []

for path in pathList:
    img = cv2.imread(os.path.join(folderPath, path))
    studentId = os.path.splitext(path)[0]

    if img is not None:
        imgList.append(img)
        studentIds.append(studentId)

def FindEncoding(imagesList, ids):
    encodeList = []
    validIds = []

    for img, studentId in zip(imagesList, ids):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        encodes = face_recognition.face_encodings(img)

        if len(encodes) > 0:
            encodeList.append(encodes[0])
            validIds.append(studentId)
        else:
            print(f"⚠️ No face detected in {studentId}, skipped.")

    return encodeList, validIds

print("Encoding Started...")
encodeListKnown, studentIds = FindEncoding(imgList, studentIds)
encodeListKnownWithIds = [encodeListKnown, studentIds]
print("Encoding Complete")

with open("EncodeFile.p", 'wb') as file:
    pickle.dump(encodeListKnownWithIds, file)

print("File saved")