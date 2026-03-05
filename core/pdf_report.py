from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import (
    Attendance,
    CallRecord,
    OtherCallRecord,
    ResultCallRecord,
    ResultUpload,
    StudentPracticalMark,
    StudentResult,
    Subject,
)

IST = ZoneInfo("Asia/Kolkata")


def _to_ist_parts(dt):
    if not dt:
        return "-", "-"
    local_dt = dt.astimezone(IST)
    return local_dt.strftime("%d-%m-%Y"), local_dt.strftime("%I:%M %p")


def _exam_name_for_pdf(test_name):
    if test_name == "T1":
        return "T1"
    if test_name == "T2":
        return "T2 / (T1+T2)"
    if test_name == "T3":
        return "T3 / (T1+T2+T3)"
    if test_name == "T4":
        return "T4 / (T1+T2+T3+T4)"
    if test_name == "REMEDIAL":
        return "REM"
    return str(test_name or "-")


def _sem_value_for_student(student):
    semester = ((getattr(student, "module", None) and student.module.semester) or "").strip()
    if not semester:
        return "1"
    # "Sem-1" -> "1"
    return semester.split("-")[-1].strip() or "1"


def _test_order_key(test_name):
    order = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "REMEDIAL": 5}
    return order.get((test_name or "").upper(), 99)


def _subject_order_key(subject_name):
    name = (subject_name or "").strip().lower()
    priority = ["mathematics", "java", "physics", "software engineering"]
    for idx, token in enumerate(priority, start=1):
        if token in name:
            return idx
    return 99


def _result_thresholds(test_name):
    test_name = (test_name or "").upper()
    if test_name == "T1":
        return 9, 9
    if test_name == "T2":
        return 9, 18
    if test_name == "T3":
        return 9, 27
    if test_name == "T4":
        return 18, 35
    return 35, 35


def _split_attendance_remarks(raw_text):
    text = (raw_text or "").strip()
    if "PARENT::" in text and "||FACULTY::" in text:
        parts = text.split("||FACULTY::", 1)
        parent_text = parts[0].replace("PARENT::", "", 1).strip() or "-"
        faculty_text = parts[1].strip() or "-"
        return parent_text, faculty_text
    return text or "-", "Student will come regularly"


def _header_text_style():
    return ParagraphStyle(
        "header_text",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        alignment=1,
    )


def _cell_text_style():
    return ParagraphStyle(
        "cell_text",
        fontName="Helvetica",
        fontSize=7.4,
        leading=9,
        alignment=0,
    )


def _p(text, style):
    return Paragraph(str(text or "-"), style)


def _table_style():
    return TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#1f2d3d")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d8e3f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (1, -1), "CENTER"),
            ("ALIGN", (2, 1), (3, -1), "CENTER"),
            ("ALIGN", (-1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ]
    )


def _title(style_sheet, text):
    return Paragraph(f"<b>{text}</b>", style_sheet["Title"])


def _footer_page_label(page_no):
    # Hard-copy aligned numbering requested by user.
    # Typical generated flow:
    # 1: Less attendance, 2: Poor result, 3: Other calls, 4: SIF marks
    mapping = {
        1: 18,
        2: 26,
        3: 30,
        4: 6,
    }
    return mapping.get(page_no, page_no)


def _draw_footer(canvas, doc, student):
    page_no = canvas.getPageNumber()
    width, _height = landscape(A4)
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#334155"))
    canvas.drawString(doc.leftMargin, 10, f"Page { _footer_page_label(page_no) }")
    right_text = f"{student.enrollment} - {student.name}"
    canvas.drawRightString(width - doc.rightMargin, 10, right_text)
    canvas.restoreState()


def _subject_priority(subject):
    key = ((subject.short_name or subject.name or "").strip().lower()).replace(" ", "")
    order = ["maths1", "maths", "phy", "physics", "java1", "java", "se", "es", "iot", "cws"]
    for idx, token in enumerate(order, start=1):
        if token in key:
            return idx
    return 99


def _ordered_subjects(module):
    subjects = list(Subject.objects.filter(module=module, is_active=True))
    subjects.sort(key=lambda s: ((s.display_order if s.display_order and s.display_order > 0 else 999999), _subject_priority(s), (s.short_name or s.name or "").lower()))
    return subjects


def _fmt_mark(v):
    if v is None:
        return "-"
    try:
        if float(v).is_integer():
            return str(int(v))
        return str(round(float(v), 2))
    except Exception:
        return str(v)


def _latest_student_result(student, subject):
    upload = (
        ResultUpload.objects.filter(module=student.module, subject=subject)
        .order_by("-uploaded_at")
        .first()
    )
    if not upload:
        return None
    return StudentResult.objects.filter(upload=upload, student=student).first()


def _sif_marks_rows(student):
    subjects = _ordered_subjects(student.module)
    practical_map = {
        pm.subject_id: pm
        for pm in StudentPracticalMark.objects.filter(module=student.module, student=student).select_related("subject")
    }
    rows = []
    for s in subjects:
        short = (s.short_name or s.name).strip()
        pm = practical_map.get(s.id)
        sr = _latest_student_result(student, s)
        attendance = _fmt_mark(pm.attendance_percentage) if pm and pm.attendance_percentage is not None else "-"

        t1 = sr.marks_t1 if sr and sr.marks_t1 is not None else (sr.marks_current if sr and sr.upload.test_name == "T1" else None)
        t2 = sr.marks_t2 if sr and sr.marks_t2 is not None else (sr.marks_current if sr and sr.upload.test_name == "T2" else None)
        t3 = sr.marks_t3 if sr and sr.marks_t3 is not None else (sr.marks_current if sr and sr.upload.test_name == "T3" else None)
        t4 = sr.marks_t4 if sr and sr.marks_t4 is not None else (sr.marks_current if sr and sr.upload.test_name == "T4" else None)
        rows.append(
            [f"{short}-TH", _fmt_mark(t1), _fmt_mark(t2), _fmt_mark(t3), _fmt_mark(t4), _fmt_mark(sr.marks_total if sr else None), attendance]
        )
        rows.append(
            [f"{short}-PR", "-", "-", "-", "-", _fmt_mark(pm.pr_marks) if pm and pm.pr_marks is not None else "-", attendance]
        )
    return rows


def generate_student_pdf(response, student):
    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=16,
    )
    elements = []
    styles = getSampleStyleSheet()
    h_style = _header_text_style()
    c_style = _cell_text_style()
    sem_value = _sem_value_for_student(student)

    # ---------------- Attendance Calls ----------------
    elements.append(_title(styles, "Telephonic Interaction with Institute for Less Attendance"))
    elements.append(Spacer(1, 8))

    attendance_headers = [
        "Sr No",
        "Sem",
        "Date",
        "Time & Duration (Round up in Minutes only)",
        "Discussed with Father / Mother / Sister / Brother / Guardian (Relation)",
        "Teaching Week No (As Per Academic Calendar)",
        "% of Attend.",
        "Parents Remarks",
        "Faculty Remarks",
        "Faculty Name & Sign",
    ]
    attendance_data = [[_p(x, h_style) for x in attendance_headers]]
    attendance_calls = CallRecord.objects.filter(student=student, final_status__isnull=False).order_by("week_no", "id")

    sr = 1
    for call in attendance_calls:
        att = Attendance.objects.filter(student=student, week_no=call.week_no).first()
        call_dt = call.attempt2_time or call.attempt1_time or call.created_at
        date, time = _to_ist_parts(call_dt)
        duration = (call.duration or "").strip()
        discussed = (call.talked_with or "-").title()
        percent = f"W:{round(att.week_percentage, 2)} / O:{round(att.overall_percentage, 2)}" if att else "-"
        parent_remark, faculty_remark = _split_attendance_remarks(call.parent_reason)

        attendance_data.append(
            [
                _p(sr, c_style),
                _p(sem_value, c_style),
                _p(date, c_style),
                _p(f"{time} ({duration})" if duration else time, c_style),
                _p(discussed, c_style),
                _p(call.week_no, c_style),
                _p(percent, c_style),
                _p(parent_remark, c_style),
                _p(faculty_remark, c_style),
                _p("", c_style),
            ]
        )
        sr += 1

    attendance_widths = [26, 24, 52, 82, 112, 66, 50, 148, 104, 52]
    attendance_table = Table(attendance_data, colWidths=attendance_widths, repeatRows=1)
    attendance_table.setStyle(_table_style())
    elements.append(attendance_table)

    # ---------------- Poor Result Calls ----------------
    elements.append(PageBreak())
    elements.append(_title(styles, "Telephonic Interaction with Institute for Poor Result"))
    elements.append(Spacer(1, 8))

    result_headers = [
        "Sr No",
        "Sem",
        "Date",
        "Time & Duration (Round up in Minutes only)",
        "Discussed with Father / Mother / Sister / Brother / Guardian (Relation)",
        "Name of Exam (T1/T2/(T1+T2)/T3/(T1+T2+T3)/T4/Total/Improvement/Others)",
        "Subject name in which failed (Secured Marks / Total Marks)",
        "Parents / Faculty Remarks",
        "Faculty Name & Sign",
    ]
    result_data = [[_p(x, h_style) for x in result_headers]]
    result_calls_qs = ResultCallRecord.objects.filter(student=student, final_status__isnull=False).select_related(
        "upload", "upload__subject"
    )
    result_calls = sorted(
        result_calls_qs,
        key=lambda call: (
            _test_order_key(call.upload.test_name if call.upload else ""),
            _subject_order_key(call.upload.subject.name if call.upload and call.upload.subject else ""),
            call.upload.uploaded_at if call.upload else call.created_at,
            call.id,
        ),
    )
    poor_result_direct_calls = OtherCallRecord.objects.filter(
        student=student,
        final_status__isnull=False,
        call_category="poor_result",
    ).order_by("updated_at", "id")

    merged_result_rows = []
    for call in result_calls:
        merged_result_rows.append(
            {
                "ts": call.attempt2_time or call.attempt1_time or call.created_at,
                "exam": _exam_name_for_pdf(call.upload.test_name if call.upload else ""),
                "subject": (
                    f"{(call.upload.subject.name if call.upload and call.upload.subject else '-')} "
                    f"({call.marks_current or 0}/{call.marks_total if call.marks_total is not None else '-'})"
                ),
                "talked_with": call.talked_with,
                "duration": call.duration,
                "remark": call.parent_reason or "-",
                "id": call.id,
            }
        )
    for call in poor_result_direct_calls:
        obtained = "-" if call.marks_obtained is None else call.marks_obtained
        out_of = "-" if call.marks_out_of is None else call.marks_out_of
        merged_result_rows.append(
            {
                "ts": call.attempt2_time or call.attempt1_time or call.updated_at or call.created_at,
                "exam": call.exam_name or "-",
                "subject": f"{call.subject_name or '-'} ({obtained}/{out_of})",
                "talked_with": call.talked_with,
                "duration": call.duration,
                "remark": call.parent_remark or "-",
                "id": call.id + 1000000,
            }
        )

    merged_result_rows = sorted(merged_result_rows, key=lambda x: (x["ts"], x["id"]))
    sr = 1
    for row in merged_result_rows:
        date, time = _to_ist_parts(row["ts"])
        duration = (row["duration"] or "").strip()
        discussed = (row["talked_with"] or "-").title()
        result_data.append(
            [
                _p(sr, c_style),
                _p(sem_value, c_style),
                _p(date, c_style),
                _p(f"{time} ({duration})" if duration else time, c_style),
                _p(discussed, c_style),
                _p(row["exam"], c_style),
                _p(row["subject"], c_style),
                _p(row["remark"], c_style),
                _p("", c_style),
            ]
        )
        sr += 1

    result_widths = [26, 24, 48, 78, 98, 126, 132, 138, 52]
    result_table = Table(result_data, colWidths=result_widths, repeatRows=1)
    result_table.setStyle(_table_style())
    elements.append(result_table)

    # ---------------- Direct Calls ----------------
    elements.append(PageBreak())
    elements.append(_title(styles, "Telephonic Interaction with Institute for Direct Calls"))
    elements.append(Spacer(1, 8))

    other_headers = [
        "Sr No",
        "Sem",
        "Date",
        "Time & Duration (Round up in Minutes only)",
        "Discussed with Student / Father / Mother",
        "Reason for Phone Call",
        "Parents / Faculty Remarks",
        "Faculty Name & Sign",
    ]
    other_data = [[_p(x, h_style) for x in other_headers]]
    other_calls = OtherCallRecord.objects.filter(student=student, final_status__isnull=False).order_by("updated_at", "id")

    sr = 1
    for call in other_calls:
        call_dt = call.attempt2_time or call.attempt1_time or call.updated_at or call.created_at
        date, time = _to_ist_parts(call_dt)
        duration = (call.duration or "").strip()
        discussed = (call.talked_with or "-").title()
        other_data.append(
            [
                _p(sr, c_style),
                _p(sem_value, c_style),
                _p(date, c_style),
                _p(f"{time} ({duration})" if duration else time, c_style),
                _p(discussed, c_style),
                _p(call.call_done_reason or "-", c_style),
                _p(call.parent_remark or "-", c_style),
                _p("", c_style),
            ]
        )
        sr += 1

    other_widths = [30, 26, 56, 96, 108, 216, 162, 58]
    other_table = Table(other_data, colWidths=other_widths, repeatRows=1)
    other_table.setStyle(_table_style())
    elements.append(other_table)

    # ---------------- SIF Marks (TH/PR + Attendance) ----------------
    elements.append(PageBreak())
    elements.append(_title(styles, "Regular Result (Theory + Practical)"))
    elements.append(Spacer(1, 8))

    marks_headers = [
        "Sub Name",
        "T1 CCE (25)",
        "T2 CCE (25)",
        "T3 CCE (25)",
        "T4 SEE (50)",
        "Final Total (100)",
        "Attendance %",
    ]
    marks_data = [[_p(x, h_style) for x in marks_headers]]
    marks_rows = _sif_marks_rows(student)
    for r in marks_rows:
        marks_data.append([_p(r[0], c_style), _p(r[1], c_style), _p(r[2], c_style), _p(r[3], c_style), _p(r[4], c_style), _p(r[5], c_style), _p(r[6], c_style)])

    marks_widths = [150, 72, 72, 72, 72, 88, 78]
    marks_table = Table(marks_data, colWidths=marks_widths, repeatRows=1)
    marks_style = _table_style()
    for row_idx in range(1, len(marks_data), 2):
        if row_idx + 1 < len(marks_data):
            marks_style.add("SPAN", (6, row_idx), (6, row_idx + 1))
            marks_style.add("VALIGN", (6, row_idx), (6, row_idx + 1), "MIDDLE")
    marks_table.setStyle(marks_style)
    elements.append(marks_table)

    footer = lambda c, d: _draw_footer(c, d, student)
    doc.build(elements, onFirstPage=footer, onLaterPages=footer)


def generate_student_prefilled_pdf(response, student):
    """
    Mentor helper PDF:
    - Pre-fills attendance percentages week-wise.
    - Pre-fills failed result rows using Either-rule:
      (current_fail OR cumulative_fail) by test thresholds.
    - Keeps date/time/discussed/remarks/sign blank for manual verification.
    """
    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=16,
    )
    elements = []
    styles = getSampleStyleSheet()
    h_style = _header_text_style()
    c_style = _cell_text_style()
    sem_value = _sem_value_for_student(student)

    elements.append(_title(styles, f"Pre-filled SIF - {student.name} ({student.enrollment})"))
    elements.append(Spacer(1, 8))

    # ---------------- Attendance (Prefilled %) ----------------
    elements.append(_title(styles, "Telephonic Interaction with Institute for Less Attendance"))
    elements.append(Spacer(1, 6))

    attendance_headers = [
        "Sr No",
        "Sem",
        "Date",
        "Time & Duration (Round up in Minutes only)",
        "Discussed with Father / Mother / Sister / Brother / Guardian (Relation)",
        "Teaching Week No (As Per Academic Calendar)",
        "% of Attend.",
        "Parents Remarks",
        "Faculty Remarks",
        "Faculty Name & Sign",
    ]
    attendance_data = [[_p(x, h_style) for x in attendance_headers]]
    rows = Attendance.objects.filter(student=student).order_by("week_no")
    sr = 1
    for a in rows:
        if a.week_percentage >= 80 and a.overall_percentage >= 80:
            continue
        percent = f"W:{round(a.week_percentage, 2)} / O:{round(a.overall_percentage, 2)}"
        attendance_data.append(
            [
                _p(sr, c_style),
                _p(sem_value, c_style),
                _p("", c_style),
                _p("", c_style),
                _p("", c_style),
                _p(a.week_no, c_style),
                _p(percent, c_style),
                _p("", c_style),
                _p("", c_style),
                _p("", c_style),
            ]
        )
        sr += 1

    attendance_widths = [26, 24, 52, 82, 112, 66, 50, 148, 104, 52]
    attendance_table = Table(attendance_data, colWidths=attendance_widths, repeatRows=1)
    attendance_table.setStyle(_table_style())
    elements.append(attendance_table)

    # ---------------- Poor Result (Prefilled failed-only) ----------------
    elements.append(PageBreak())
    elements.append(_title(styles, "Telephonic Interaction with Institute for Poor Result"))
    elements.append(Spacer(1, 6))

    result_headers = [
        "Sr No",
        "Sem",
        "Date",
        "Time & Duration (Round up in Minutes only)",
        "Discussed with Father / Mother / Sister / Brother / Guardian (Relation)",
        "Name of Exam (T1/T2/(T1+T2)/T3/(T1+T2+T3)/T4/Total/Improvement/Others)",
        "Subject name in which failed (Secured Marks / Total Marks)",
        "Parents / Faculty Remarks",
        "Faculty Name & Sign",
    ]
    result_data = [[_p(x, h_style) for x in result_headers]]
    result_rows_qs = StudentResult.objects.filter(student=student).select_related("upload", "upload__subject")
    result_rows = sorted(
        result_rows_qs,
        key=lambda r: (
            _test_order_key(r.upload.test_name if r.upload else ""),
            _subject_order_key(r.upload.subject.name if r.upload and r.upload.subject else ""),
            r.upload.uploaded_at if r.upload else r.id,
            r.id,
        ),
    )

    sr = 1
    for r in result_rows:
        if not r.upload:
            continue
        cur_thr, total_thr = _result_thresholds(r.upload.test_name)
        current_fail = r.marks_current is not None and r.marks_current < cur_thr
        total_fail = r.marks_total is not None and r.marks_total < total_thr
        if not (current_fail or total_fail):
            continue

        exam = _exam_name_for_pdf(r.upload.test_name)
        subject = r.upload.subject.name if r.upload.subject else "-"
        total_mark = r.marks_total if r.marks_total is not None else "-"
        subject_text = f"{subject} ({r.marks_current if r.marks_current is not None else '-'} / {total_mark})"

        result_data.append(
            [
                _p(sr, c_style),
                _p(sem_value, c_style),
                _p("", c_style),
                _p("", c_style),
                _p("", c_style),
                _p(exam, c_style),
                _p(subject_text, c_style),
                _p("", c_style),
                _p("", c_style),
            ]
        )
        sr += 1

    result_widths = [26, 24, 48, 78, 98, 126, 132, 138, 52]
    result_table = Table(result_data, colWidths=result_widths, repeatRows=1)
    result_table.setStyle(_table_style())
    elements.append(result_table)

    # ---------------- SIF Marks (TH/PR + Attendance) ----------------
    elements.append(PageBreak())
    elements.append(_title(styles, "Regular Result (Theory + Practical)"))
    elements.append(Spacer(1, 8))

    marks_headers = [
        "Sub Name",
        "T1 CCE (25)",
        "T2 CCE (25)",
        "T3 CCE (25)",
        "T4 SEE (50)",
        "Final Total (100)",
        "Attendance %",
    ]
    marks_data = [[_p(x, h_style) for x in marks_headers]]
    for r in _sif_marks_rows(student):
        marks_data.append([_p(r[0], c_style), _p(r[1], c_style), _p(r[2], c_style), _p(r[3], c_style), _p(r[4], c_style), _p(r[5], c_style), _p(r[6], c_style)])

    marks_widths = [150, 72, 72, 72, 72, 88, 78]
    marks_table = Table(marks_data, colWidths=marks_widths, repeatRows=1)
    marks_style = _table_style()
    for row_idx in range(1, len(marks_data), 2):
        if row_idx + 1 < len(marks_data):
            marks_style.add("SPAN", (6, row_idx), (6, row_idx + 1))
            marks_style.add("VALIGN", (6, row_idx), (6, row_idx + 1), "MIDDLE")
    marks_table.setStyle(marks_style)
    elements.append(marks_table)
    footer = lambda c, d: _draw_footer(c, d, student)
    doc.build(elements, onFirstPage=footer, onLaterPages=footer)

