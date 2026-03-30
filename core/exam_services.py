from decimal import Decimal, InvalidOperation
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .models import ExamBlock, ExamBlockStudent, ExamMarkEntry, ExamSeatingBlock, ExamTimetableEntry, ResultCallRecord, ResultUpload, StudentResult


def exam_phase_defaults(test_name):
    test = (test_name or "").upper()
    if test in {"T1", "T2", "T3"}:
        index = {"T1": 1, "T2": 2, "T3": 3}[test]
        return {
            "max_marks": Decimal("25"),
            "pass_marks": Decimal("9"),
            "total_pass_marks": Decimal(str(9 * index)),
        }
    if test == "T4":
        return {
            "max_marks": Decimal("50"),
            "pass_marks": Decimal("18"),
            "total_pass_marks": Decimal("35"),
        }
    return {
        "max_marks": Decimal("100"),
        "pass_marks": Decimal("35"),
        "total_pass_marks": Decimal("35"),
    }


def parse_exam_mark(raw_value, max_marks):
    value = (raw_value or "").strip().upper()
    if not value:
        return None, None, False
    if value == "AB":
        return "AB", None, True
    try:
        marks = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Enter only number or AB.") from exc
    if marks < 0:
        raise ValueError("Marks cannot be negative.")
    if marks > Decimal(str(max_marks)):
        raise ValueError(f"Marks cannot be more than {max_marks}.")
    if (marks * 2) != (marks * 2).quantize(Decimal("1")):
        raise ValueError("Only .5 decimals are allowed.")
    return value, marks, False


def entry_opens_at(entry):
    return timezone.make_aware(datetime.combine(entry.exam_date, entry.start_time))


def can_edit_entry_now(entry):
    now = timezone.localtime()
    if entry.is_locked:
        return False, "Marks entry is locked."
    if now < entry_opens_at(entry):
        return False, "Marks entry will open at exam start time."
    if now > entry.entry_deadline:
        return False, "Marks entry deadline has passed."
    return True, ""


def build_block_students(block, manual_student_ids=None):
    entry = block.timetable_entry
    selected = resolve_block_students(
        entry.session.module,
        block.block_type,
        block.batch,
        block.enrollment_start,
        block.enrollment_end,
        manual_student_ids=manual_student_ids,
    )

    existing_ids = set(
        ExamBlockStudent.objects.filter(block__timetable_entry=entry)
        .exclude(block=block)
        .values_list("student_id", flat=True)
    )
    final_students = [student for student in selected if student.id not in existing_ids]
    ExamBlockStudent.objects.filter(block=block).delete()
    ExamBlockStudent.objects.bulk_create(
        [ExamBlockStudent(block=block, student=student) for student in final_students],
        ignore_conflicts=True,
    )
    return final_students, len(selected) - len(final_students)


def resolve_block_students(module, block_type, batch, enrollment_start, enrollment_end, manual_student_ids=None):
    module_students = module.students.all().select_related("mentor").order_by("roll_no", "name")
    if block_type == "batch":
        selected = list(module_students.filter(batch__iexact=(batch or "").strip()))
    elif block_type == "range":
        start = (enrollment_start or "").strip()
        end = (enrollment_end or "").strip()
        selected = list(module_students.filter(enrollment__gte=start, enrollment__lte=end).order_by("enrollment"))
    else:
        selected = list(module_students.filter(id__in=list(manual_student_ids or [])))
    return selected


def exam_stats_for_block(block):
    links = list(block.student_links.select_related("student").order_by("student__roll_no", "student__name"))
    marks = {
        row.student_id: row
        for row in ExamMarkEntry.objects.filter(block=block).select_related("student")
    }
    total = len(links)
    appeared = absent = passed = failed = pending = 0
    for link in links:
        row = marks.get(link.student_id)
        if not row or (not row.is_absent and row.marks_obtained is None):
            pending += 1
            continue
        if row.is_absent:
            absent += 1
            continue
        appeared += 1
        if row.marks_obtained is not None and row.marks_obtained < block.timetable_entry.pass_marks:
            failed += 1
        else:
            passed += 1
    return {
        "total": total,
        "appeared": appeared,
        "absent": absent,
        "passed": passed,
        "failed": failed,
        "pending": pending,
    }


def compiled_rows_for_entry(entry):
    result_rows = _result_payload_for_entry(entry)
    result_map = {row["student"].id: row for row in result_rows}
    rows = []
    links = (
        ExamBlockStudent.objects.filter(block__timetable_entry=entry)
        .select_related("student", "student__mentor", "block")
        .order_by("student__roll_no", "student__enrollment", "student__name")
    )
    for index, link in enumerate(links, start=1):
        student = link.student
        result_row = result_map.get(student.id, {})
        current_mark = result_row.get("current_mark")
        total_mark = result_row.get("mtotal")
        rows.append(
            {
                "sr_no": index,
                "branch": (student.batch or "").strip(),
                "enrollment": student.enrollment,
                "name": student.name,
                "roll_no": student.roll_no,
                "division": (student.division or "").strip(),
                "mentor_short_name": getattr(student.mentor, "name", "") or "",
                "marks_display": "AB" if result_row.get("is_absent") else (current_mark if current_mark is not None else ""),
                "cumulative_display": "" if result_row.get("is_absent") else (total_mark if total_mark is not None else ""),
                "is_absent": bool(result_row.get("is_absent")),
            }
        )
    return rows


def _manual_student_ids_from_seating_block(module, seating_block):
    manual_enrollments = [
        value.strip()
        for value in (seating_block.manual_enrollments or "").replace("\n", ",").split(",")
        if value.strip()
    ]
    if not manual_enrollments:
        return []
    return list(module.students.filter(enrollment__in=manual_enrollments).values_list("id", flat=True))


def sync_exam_blocks_from_seating(entry):
    seating_map = {
        (block.delivery_mode, (block.block_number or "").strip()): block
        for block in ExamSeatingBlock.objects.filter(session=entry.session, is_preview=False)
    }
    exam_blocks = list(entry.blocks.select_related("evaluator").order_by("delivery_mode", "block_number", "id"))
    assigned_student_ids = set()

    for block in exam_blocks:
        seating_block = seating_map.get((block.delivery_mode, (block.block_number or "").strip()))
        if not seating_block:
            continue

        block.room = seating_block.room
        block.lab = seating_block.lab
        block.block_type = seating_block.block_type
        block.name = seating_block.name or block.name
        block.batch = seating_block.batch
        block.enrollment_start = seating_block.enrollment_start
        block.enrollment_end = seating_block.enrollment_end
        block.save(update_fields=["room", "lab", "block_type", "name", "batch", "enrollment_start", "enrollment_end"])

        selected_students = resolve_block_students(
            entry.session.module,
            seating_block.block_type,
            seating_block.batch,
            seating_block.enrollment_start,
            seating_block.enrollment_end,
            manual_student_ids=_manual_student_ids_from_seating_block(entry.session.module, seating_block),
        )
        final_student_ids = []
        for student in selected_students:
            if student.id in assigned_student_ids:
                continue
            final_student_ids.append(student.id)
            assigned_student_ids.add(student.id)

        current_ids = set(block.student_links.values_list("student_id", flat=True))
        target_ids = set(final_student_ids)

        stale_ids = current_ids - target_ids
        if stale_ids:
            ExamMarkEntry.objects.filter(block=block, student_id__in=stale_ids).delete()
            ExamBlockStudent.objects.filter(block=block, student_id__in=stale_ids).delete()

        new_ids = target_ids - current_ids
        if new_ids:
            ExamBlockStudent.objects.bulk_create(
                [ExamBlockStudent(block=block, student_id=student_id) for student_id in final_student_ids if student_id in new_ids],
                ignore_conflicts=True,
            )

    return exam_blocks


def _previous_mark(upload, student, test_name):
    previous_upload = (
        ResultUpload.objects.filter(
            module=upload.module,
            test_name=test_name,
            subject=upload.subject,
        )
        .order_by("-uploaded_at")
        .first()
    )
    if not previous_upload:
        return None
    previous = StudentResult.objects.filter(upload=previous_upload, student=student).first()
    return previous.marks_current if previous else None


def _result_payload_for_entry(entry):
    block_student_ids = set(
        ExamBlockStudent.objects.filter(block__timetable_entry=entry).values_list("student_id", flat=True)
    )
    rows = []
    for student in entry.session.module.students.filter(id__in=block_student_ids).order_by("roll_no", "enrollment"):
        mark = (
            ExamMarkEntry.objects.filter(timetable_entry=entry, student=student)
            .order_by("-updated_at", "-id")
            .first()
        )
        if not mark:
            continue
        current_mark = None if mark.is_absent else float(mark.marks_obtained)
        m1 = _previous_mark(entry.published_upload or ResultUpload(module=entry.session.module, subject=entry.subject), student, "T1")
        m2 = _previous_mark(entry.published_upload or ResultUpload(module=entry.session.module, subject=entry.subject), student, "T2")
        m3 = _previous_mark(entry.published_upload or ResultUpload(module=entry.session.module, subject=entry.subject), student, "T3")
        m4 = current_mark if entry.session.test_name == "T4" else None
        if entry.session.test_name == "T1":
            m1 = current_mark
            total = current_mark
        elif entry.session.test_name == "T2":
            total = (m1 or 0) + (current_mark or 0)
        elif entry.session.test_name == "T3":
            total = (m1 or 0) + (m2 or 0) + (current_mark or 0)
        elif entry.session.test_name == "T4":
            total = (m1 or 0) + (m2 or 0) + (m3 or 0) + ((current_mark or 0) / 2.0)
        else:
            total = current_mark
        fail_flag = False
        fail_reason = ""
        if not mark.is_absent and current_mark is not None:
            fail_flag = current_mark < float(entry.pass_marks) and total < float(entry.total_pass_marks)
            if fail_flag:
                fail_reason = (
                    f"Less than {entry.pass_marks} in {entry.session.test_name} and less than "
                    f"{entry.total_pass_marks} in total"
                )
        rows.append(
            {
                "student": student,
                "enrollment": student.enrollment,
                "current_mark": current_mark,
                "m1": m1,
                "m2": m2,
                "m3": m3,
                "m4": m4,
                "mtotal": total,
                "is_absent": mark.is_absent,
                "fail_flag": fail_flag,
                "fail_reason": fail_reason,
            }
        )
    return rows


@transaction.atomic
def publish_locked_entry(entry, locked_by):
    existing_upload = ResultUpload.objects.filter(
        module=entry.session.module,
        test_name=entry.session.test_name,
        subject=entry.subject,
    ).first()
    if existing_upload and entry.published_upload_id and existing_upload.id != entry.published_upload_id:
        raise ValueError("Existing uploaded result found for this exam and subject.")
    if existing_upload and not entry.published_upload_id:
        raise ValueError("Existing uploaded result found for this exam and subject. Delete old upload first.")

    upload, _ = ResultUpload.objects.update_or_create(
        module=entry.session.module,
        test_name=entry.session.test_name,
        subject=entry.subject,
        defaults={"uploaded_by": locked_by.username},
    )
    rows = _result_payload_for_entry(entry)
    StudentResult.objects.filter(upload=upload).delete()
    rows_failed = 0
    for row in rows:
        StudentResult.objects.create(
            upload=upload,
            student=row["student"],
            enrollment=row["enrollment"],
            marks_current=row["current_mark"],
            marks_t1=row["m1"],
            marks_t2=row["m2"],
            marks_t3=row["m3"],
            marks_t4=row["m4"],
            marks_total=row["mtotal"],
            is_absent=row["is_absent"],
            fail_flag=row["fail_flag"],
            fail_reason=row["fail_reason"],
        )
        if row["fail_flag"]:
            rows_failed += 1
            ResultCallRecord.objects.create(
                upload=upload,
                student=row["student"],
                fail_reason=row["fail_reason"],
                marks_current=row["current_mark"] or 0,
                marks_total=row["mtotal"],
            )
    upload.rows_total = len(rows)
    upload.rows_matched = len(rows)
    upload.rows_failed = rows_failed
    upload.save(update_fields=["rows_total", "rows_matched", "rows_failed", "uploaded_at", "uploaded_by"])
    entry.published_upload = upload
    entry.published_at = timezone.now()
    entry.locked_by = locked_by
    entry.locked_at = timezone.now()
    entry.is_locked = True
    entry.save(update_fields=["published_upload", "published_at", "locked_by", "locked_at", "is_locked", "updated_at"])
    return upload
