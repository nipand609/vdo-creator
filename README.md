# Video Planner — คู่มือ Deploy บน Railway

## ไฟล์ในโปรเจค
```
video-editor/
├── main.py          ← backend (FastAPI + FFmpeg)
├── requirements.txt ← Python packages
├── Dockerfile       ← สำหรับ Railway
└── templates/
    └── index.html   ← หน้าเว็บมือถือ
```

---

## ขั้นตอน Deploy (ทำครั้งเดียว ~10 นาที)

### Step 1 — สมัคร GitHub
1. เปิด github.com → กด Sign up (ฟรี)
2. สร้าง repository ใหม่ชื่อ `video-planner`
3. อัพโหลดไฟล์ทั้งหมดใน video-editor/ เข้าไป

### Step 2 — สมัคร Railway
1. เปิด railway.app → กด Login with GitHub
2. กด New Project → Deploy from GitHub repo
3. เลือก repo `video-planner`
4. Railway จะ detect Dockerfile อัตโนมัติ
5. กด Deploy → รอ ~3 นาที

### Step 3 — เปิดใช้งาน
1. ไปที่ Settings → Networking → Generate Domain
2. ได้ URL เช่น `video-planner-production.up.railway.app`
3. เปิดใน Safari/Chrome บนมือถือได้เลย!

---

## ค่าใช้จ่าย Railway
- Hobby Plan: $5/เดือน
- รวม RAM 8GB, CPU เพียงพอสำหรับ FFmpeg

---

## ฟีเจอร์ที่ได้
- อัพโหลดคลิป + แท็ก A/B roll
- เลือก pattern การสลับ 4 แบบ
- ใส่ปกรูปภาพ (แสดง 3 วิ ตอนต้น)
- เสียงพากย์: อัพโหลดไฟล์ หรือบันทึกผ่านไมค์
- ดูลำดับ preview ก่อน render
- Render จริงด้วย FFmpeg → ดาวน์โหลด MP4

## เวลา Render โดยประมาณ
- 4 คลิป 720p → ~15-30 วิ
- 10 คลิป 1080p → ~60-90 วิ
