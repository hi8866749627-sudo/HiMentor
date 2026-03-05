
# 🎓 LJ Attendance Follow-up ERP

A Django-based academic follow-up system that automates mentor calling workflow for low-attendance students.

Designed for colleges where mentors must call parents weekly and maintain records manually.

This system converts a 1–2 hour weekly manual task into a 5-minute guided workflow.

---

## 🚀 Main Purpose

In many institutes:

1. Coordinator uploads attendance Excel
2. Mentor manually finds students
3. Calls parents
4. Writes follow-up in register
5. Prepares weekly report
6. Sends WhatsApp summary

This project automates ALL of that.

---

## 👥 User Roles

### 1) Coordinator
- Upload student master (once)
- Upload weekly attendance
- View mentor performance
- Delete weeks / lock weeks
- See analytics

### 2) Mentor
- Login using short name (e.g. HDS)
- System shows only defaulters
- One-tap call parent
- Mark received / not received
- Auto retry reminder
- WhatsApp message ready
- Weekly report auto generated

---

## ⚙️ Features

### Attendance Processing
- Reads messy college Excel sheets
- Detects header automatically
- Extracts weekly & overall attendance
- Generates call list (<80%)

### Smart Call Workflow
- Tap CALL → opens dialer
- After return → mark received / not received
- After all calls → retry popup for missed parents
- WhatsApp message auto prepared

### Reports
- Mentor weekly report text
- Coordinator analytics dashboard
- Semester attendance register (dynamic columns)
- Printable student follow-up sheet (A4 landscape)

### Automation
- No manual data entry
- No manual calculations
- No copy-paste WhatsApp
- No manual registers

--- Thank you ---
