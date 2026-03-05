
# AI Context Specification — Attendance Follow-up ERP

This document describes the architecture, constraints, logic and intent of the system for AI coding assistants.

The goal is not only correctness but workflow optimization.

---

## Core Problem

Mentor-mentee attendance follow-up in colleges is a repetitive structured workflow:

1) Identify defaulters
2) Call parents
3) Record call outcome
4) Retry unreachable parents
5) Prepare weekly summary
6) Maintain semester record

Humans do this manually via Excel + registers.

System converts it into a guided state machine.

---

## System Philosophy

This is NOT a general ERP.

It is a workflow engine specialized for:

LOW ATTENDANCE FOLLOW-UP OPERATIONS

Every feature must reduce mentor cognitive load.

AI suggestions must prioritize:
- fewer clicks
- fewer decisions
- zero memory dependence
- phone-first usage

---

## Key Entities

Student
- enrollment (primary identity)
- mentor
- parent phones

Attendance
- week_no
- weekly_percentage
- overall_percentage
- call_required (derived state)

CallRecord
- student
- week_no
- attempt1_time
- attempt2_time
- final_status (received/not_received)
- parent_reason
- duration
- talked_with

WeekLock
- prevents editing past weeks

---

## Workflow State Machine

Attendance Uploaded
    ↓
CallRecord Created
    ↓
Mentor Calls
    ↓
Mark Received / Not Received
    ↓
If Not Received → Retry Group
    ↓
After Completion → Report Generated

AI must preserve this deterministic flow.

---

## Constraints

1) Data comes from unpredictable Excel formats
2) System must auto detect columns
3) Mobile UI priority > desktop UI
4) Mentors are non-technical users
5) Actions must be guided, not configurable
6) Avoid forms — prefer buttons & states

---

## UX Rules

Bad UX:
- asking user what to do next
- manual typing
- dropdown heavy interfaces

Good UX:
- system tells next action
- single button operations
- contextual popup decisions

---

## Future AI Integration (Allowed Improvements)

AI may suggest:
- auto classify parent remarks
- detect chronic defaulters
- predict dropout risk
- generate personalized messages
- speech-to-text call notes

AI must NOT:
- change workflow order
- add extra steps to mentor flow
- require training or configuration

---

## Performance Expectations

Typical dataset:
200–1200 students
15 weeks
10 mentors

SQLite acceptable.
Optimization secondary to clarity.

---

## AI Goal

This project is a workflow automation tool, not a CRUD app.

Any improvement should answer:

"Does this reduce mentor effort?"

If yes → implementable
If neutral → optional
If increases complexity → reject


