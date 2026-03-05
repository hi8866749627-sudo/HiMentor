# AI Use Cases & Test Scenarios
Attendance Follow-up ERP

This file defines real world behavioral tests.
AI assistants MUST satisfy these scenarios after any modification.

The project is workflow-driven, not feature-driven.

---

# USER TYPES

1) Coordinator
2) Mentor

No other roles exist.

---

# CORE RULE

The system is a guided weekly cycle:

Upload → Call → Retry → Report → Archive

Every feature must preserve this order.

---

# COORDINATOR USE CASES

## UC-C1 Upload Student Master

Input:
- Excel with unpredictable headers
- May contain merged cells
- May contain float phone numbers (9876543210.0)

Expected Result:
- Students created or updated
- Mentor auto created
- Phones converted to 91XXXXXXXXXX
- No duplicates by enrollment

Fail Conditions:
- Duplicate students
- Phone saved incorrectly
- Mentor blank

---

## UC-C2 Upload Attendance (Week-1)

Input:
Weekly attendance sheet only

Expected:
- Weekly % stored
- Overall % same as weekly
- Call records created for <80%
- Mentor dashboard shows students immediately

---

## UC-C3 Upload Attendance (Week-N)

Input:
Weekly + Overall sheet

Expected:
- Weekly column updated
- Overall column updated
- No duplicate call records
- Previous weeks untouched

---

## UC-C4 Delete Week

Action:
Delete Week-3

Expected:
- Week-3 attendance removed
- Week-3 call records removed
- Other weeks preserved

---

## UC-C5 Coordinator Dashboard

Expected:
- Mentor wise counts
- Pending calls visible
- Completion percentage accurate

---

# MENTOR USE CASES

## UC-M1 Login

Input:
username = mentor short name
password = shared password

Expected:
- Only own students visible
- Latest week auto selected

---

## UC-M2 View Weekly Call List

Expected:
Shows only students requiring call
Columns:
Roll | Enrollment | Name | Weekly % | Overall %

---

## UC-M3 Make Call

Action:
Tap CALL button

Expected:
- Dialer opens
- On return → result popup shown

---

## UC-M4 Mark Received

Input:
talked_with, duration, remark

Expected:
- Saved in CallRecord
- Removed from pending list

---

## UC-M5 Mark Not Received

Expected:
- Mark attempt
- After all calls → retry popup appears

---

## UC-M6 Retry Popup

Trigger:
All calls processed

Expected:
Shows only not_received students
Each has:
Call button
WhatsApp button

---

## UC-M7 WhatsApp Message

Action:
Tap WhatsApp

Expected:
Opens chat with prefilled message:
Includes name, roll, weekly %, overall %

---

## UC-M8 Weekly Report

Expected:
Auto generated text summary
Numbers must match database counts

---

# SEMESTER REGISTER USE CASE

## UC-S1 Progressive Columns

Week-1 uploaded → shows Week-1 column
Week-2 uploaded → shows Week-1 Week-2
Week-N uploaded → shows 1..N columns

No manual config allowed.

---

# MOBILE UX REQUIREMENTS

The system is primarily mobile driven.

Must support:
- Tap sized buttons
- No horizontal scrolling in call screen
- One-hand operation

Failure if:
Mentor needs to zoom or type frequently

---

# DATA INTEGRITY TESTS

After any refactor, AI must verify:

1) Enrollment uniquely identifies student
2) Week deletion does not affect other weeks
3) CallRecord belongs to correct week
4) Attendance history preserved
5) No duplicate call records

---

# AUTOMATION RULES

AI may optimize:
- parsing
- performance
- UI responsiveness

AI must NOT:
- add manual forms
- add multi-step workflows
- require configuration
- change weekly process order

---

# SUCCESS CONDITION

The system is successful if a mentor can:

Open phone → Call all parents → Send WhatsApp → Generate report

in under 5 minutes.

Any change increasing time is regression.
