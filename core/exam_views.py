from datetime import datetime
import json
from decimal import Decimal
from math import ceil
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph

from .access import can_manage_module, modules_for_user
from .exam_access import can_enter_exam_block, can_manage_exam_module, exam_modules_for_user, has_exam_section_access
from .exam_services import (
    build_block_students,
    can_edit_entry_now,
    compiled_rows_for_entry,
    entry_opens_at,
    exam_phase_defaults,
    exam_stats_for_block,
    parse_exam_mark,
    publish_locked_entry,
    resolve_block_students,
    sync_exam_blocks_from_seating,
)
from .models import (
    AcademicModule,
    CoordinatorModuleAccess,
    ExamBlock,
    ExamBlockStudent,
    ExamSeatingBlock,
    ExamFacultyProfile,
    ExamMarkEntry,
    ExamSubjectEvaluator,
    ExamTimetableEntry,
    Mentor,
    ModuleExamManager,
    ModuleExamSession,
    Student,
    Subject,
    TimetableEntry,
)


def _selected_exam_module(request):
    user = request.user
    managed_modules = list(modules_for_user(user).filter(is_active=True))
    module_choices = managed_modules or list(exam_modules_for_user(user))
    if not module_choices:
        return None, []
    requested = (request.GET.get("module_id") or request.POST.get("module_id") or "").strip()
    if requested.isdigit():
        for module in module_choices:
            if module.id == int(requested):
                request.session["current_exam_module_id"] = module.id
                return module, module_choices
    current_id = request.session.get("current_exam_module_id")
    for module in module_choices:
        if module.id == current_id:
            return module, module_choices
    request.session["current_exam_module_id"] = module_choices[0].id
    return module_choices[0], module_choices


def _module_faculty_directory(module):
    if not module:
        return [], [], []

    mentors = list(Mentor.objects.order_by("full_name", "name"))
    mentor_name_map = {(mentor.name or "").strip().lower(): mentor for mentor in mentors if (mentor.name or "").strip()}
    matching_users = {
        user.username.lower(): user
        for user in User.objects.filter(username__in=list(mentor_name_map.keys())).order_by("username")
    }

    auto_create_profiles = []
    used_short_codes = set(ExamFacultyProfile.objects.values_list("short_code", flat=True))
    for username, mentor in mentor_name_map.items():
        if hasattr(mentor, "exam_faculty_profile"):
            continue
        user = matching_users.get(username)
        short_code = (mentor.name or "").strip().upper()
        if not user or not short_code or short_code in used_short_codes:
            continue
        auto_create_profiles.append(
            ExamFacultyProfile(
                user=user,
                mentor=mentor,
                short_code=short_code,
                full_name=(mentor.full_name or "").strip(),
            )
        )
        used_short_codes.add(short_code)
    if auto_create_profiles:
        ExamFacultyProfile.objects.bulk_create(auto_create_profiles, ignore_conflicts=True)

    profiles = list(
        ExamFacultyProfile.objects.filter(is_active=True)
        .select_related("user", "mentor")
        .order_by("full_name", "short_code")
    )
    profile_mentor_ids = {profile.mentor_id for profile in profiles if profile.mentor_id}
    unregistered_names = [
        (mentor.name or "").strip().upper()
        for mentor in mentors
        if mentor.id not in profile_mentor_ids
    ]
    return mentors, profiles, unregistered_names


def _manager_candidate_users(module):
    coordinator_ids = CoordinatorModuleAccess.objects.filter(module=module).values_list("coordinator_id", flat=True)
    profile_users = list(
        ExamFacultyProfile.objects.select_related("user", "mentor").order_by("short_code")
    )
    mentor_user_ids = list(
        User.objects.filter(username__in=[name.lower() for name in Mentor.objects.values_list("name", flat=True)]).values_list("id", flat=True)
    )
    user_ids = set(coordinator_ids)
    user_ids.update(profile.user_id for profile in profile_users)
    user_ids.update(mentor_user_ids)
    users = list(User.objects.filter(id__in=user_ids).order_by("username"))

    profile_labels = {
        profile.user_id: f"{profile.short_code} - {(profile.full_name or getattr(profile.mentor, 'full_name', '') or '').strip()}".strip(" -")
        for profile in profile_users
    }
    candidates = []
    seen = set()
    for user in users:
        label = profile_labels.get(user.id) or user.username
        if user.id in seen:
            continue
        seen.add(user.id)
        candidates.append({"id": user.id, "label": label})
    return sorted(candidates, key=lambda item: item["label"].lower())


def _infer_branch_label(student, module):
    # Student Master stores branch in `batch`; `division` is a separate grouping field.
    branch_value = (getattr(student, "batch", "") or "").strip()
    if branch_value:
        return branch_value.upper()

    candidates = [
        (getattr(module, "variant", "") or "").strip(),
        (getattr(module, "name", "") or "").strip(),
    ]
    branch_tokens = [
        "AIML",
        "AI",
        "CSE",
        "CE",
        "IT",
        "ME",
        "EC",
        "ECE",
        "EE",
        "CIVIL",
    ]
    for candidate in candidates:
        upper = candidate.upper()
        for token in branch_tokens:
            if token in upper:
                return token
    return (getattr(module, "variant", "") or getattr(module, "year_level", "") or "GEN").split("-")[-1].upper()


def _branch_count_summary(students, module):
    counts = {}
    for student in students:
        label = _infer_branch_label(student, module)
        counts[label] = counts.get(label, 0) + 1
    summary_rows = [
        {"branch": branch, "count": count, "label": f"{branch}-{count:02d}"}
        for branch, count in sorted(counts.items())
    ]
    if not summary_rows:
        display = "-"
    elif len(summary_rows) == 1:
        display = summary_rows[0]["label"]
    else:
        display = "\n".join(row["label"] for row in summary_rows)
    return summary_rows, display


def _branch_detail_rows(students, module):
    grouped = {}
    for student in students:
        label = _infer_branch_label(student, module)
        grouped.setdefault(label, []).append(student)

    detail_rows = []
    for branch in sorted(grouped):
        branch_students = grouped[branch]
        enrollments = sorted(
            [(getattr(student, "enrollment", "") or "").strip() for student in branch_students if (getattr(student, "enrollment", "") or "").strip()]
        )
        if enrollments:
            range_display = f"{enrollments[0]} - {enrollments[-1]}"
        else:
            range_display = "-"
        detail_rows.append(
            {
                "branch": branch,
                "count": len(branch_students),
                "label": f"{branch}-{len(branch_students):02d}",
                "range_display": range_display,
            }
        )
    return detail_rows


def _resolve_evaluator_profile(value, profiles):
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.upper()
    for profile in profiles:
        short_code = (profile.short_code or "").strip().upper()
        full_name = (profile.full_name or getattr(profile.mentor, "full_name", "") or "").strip().upper()
        combined = f"{short_code} - {full_name}".strip(" -")
        if normalized in {short_code, full_name, combined}:
            return profile
    return None


def _subject_code_for_entry(entry):
    short_name = (entry.subject.short_name or "").strip()
    if short_name:
        return short_name
    return ""


def _subject_faculty_names(entry):
    names = sorted(
        {
            (faculty or "").strip()
            for faculty in TimetableEntry.objects.filter(module=entry.session.module, subject__iexact=entry.subject.name, is_active=True)
            .values_list("faculty", flat=True)
            if (faculty or "").strip()
        }
    )
    return ", ".join(names)


def _entry_compiled_header(entry, module):
    college_name = ""
    if getattr(module, "year_scope_id", None) and getattr(module.year_scope, "college_id", None):
        college_name = (module.year_scope.college.name or "").upper()
    if not college_name:
        college_name = "L J INSTITUTE OF ENGINEERING AND TECHNOLOGY, AHMEDABAD"
    batch_line = module.name
    year_line = f"Engineering Students Result_{module.semester}-{module.academic_batch}"
    subject_line = entry.subject.name
    code_line = _subject_code_for_entry(entry)
    faculty_line = _subject_faculty_names(entry)
    current_total_label = f"Marks (/{entry.max_marks})"
    cumulative_total = "100"
    if entry.session.test_name == "T1":
        cumulative_total = "25"
    elif entry.session.test_name == "T2":
        cumulative_total = "50"
    elif entry.session.test_name == "T3":
        cumulative_total = "75"
    return {
        "college_name": college_name,
        "batch_line": batch_line,
        "year_line": year_line,
        "subject_line": subject_line,
        "code_line": code_line,
        "faculty_line": faculty_line,
        "current_total_label": current_total_label,
        "cumulative_label": f"Cummulative(/ {cumulative_total})",
    }


def _entry_block_statuses(entry):
    rows = []
    for block in entry.blocks.select_related("evaluator").order_by("delivery_mode", "block_number", "id"):
        stats = exam_stats_for_block(block)
        is_done = stats["total"] > 0 and stats["pending"] == 0
        rows.append(
            {
                "block": block,
                "stats": stats,
                "is_done": is_done,
                "completed_count": max(stats["total"] - stats["pending"], 0),
            }
        )
    return rows


def _render_entry_compiled_excel(entry):
    rows = compiled_rows_for_entry(entry)
    meta = _entry_compiled_header(entry, entry.session.module)
    wb = Workbook()
    ws = wb.active
    ws.title = "Compiled"
    ws.append([meta["college_name"]])
    ws.append([meta["batch_line"]])
    ws.append([meta["year_line"]])
    ws.append([f"Subject Name : {meta['subject_line']}"])
    ws.append([f"Subject Code : {meta['code_line']}"])
    ws.append([f"Name of Subject Faculty (For All Division) : {meta['faculty_line']}"])
    ws.append([])
    ws.append([
        "Sr No",
        "Branch",
        "ENROLLMENT NO",
        "NAME OF STUDENT",
        "Roll No",
        "Div",
        "Short Name of Mentor",
        meta["current_total_label"],
        meta["cumulative_label"],
    ])
    for row in rows:
        ws.append([
            row["sr_no"],
            row["branch"],
            row["enrollment"],
            row["name"],
            row["roll_no"],
            row["division"],
            row["mentor_short_name"],
            row["marks_display"],
            row["cumulative_display"],
        ])
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="compiled_{entry.session.test_name}_{entry.subject.name}.xlsx"'
    wb.save(response)
    return response


def _render_entry_compiled_pdf(entry):
    rows = compiled_rows_for_entry(entry)
    meta = _entry_compiled_header(entry, entry.session.module)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="compiled_{entry.session.test_name}_{entry.subject.name}.pdf"'
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=12, rightMargin=12, topMargin=12, bottomMargin=12)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(meta["college_name"], styles["Heading3"]),
        Paragraph(meta["batch_line"], styles["BodyText"]),
        Paragraph(meta["year_line"], styles["BodyText"]),
        Spacer(1, 6),
        Paragraph(f"Subject Name : {meta['subject_line']}", styles["BodyText"]),
        Paragraph(f"Subject Code : {meta['code_line']}", styles["BodyText"]),
        Paragraph(f"Name of Subject Faculty (For All Division) : {meta['faculty_line']}", styles["BodyText"]),
        Spacer(1, 10),
    ]
    table_data = [[
        "Sr No",
        "Branch",
        "ENROLLMENT NO",
        "NAME OF STUDENT",
        "Roll No",
        "Div",
        "Short Name of Mentor",
        meta["current_total_label"],
        meta["cumulative_label"],
    ]]
    for row in rows:
        table_data.append([
            row["sr_no"],
            row["branch"],
            row["enrollment"],
            row["name"],
            row["roll_no"] or "",
            row["division"],
            row["mentor_short_name"],
            row["marks_display"],
            row["cumulative_display"],
        ])
    table = Table(table_data, repeatRows=1, colWidths=[40, 60, 95, 170, 45, 45, 80, 70, 85])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    doc.build(story)
    return response


@login_required
@require_http_methods(["GET", "POST"])
def exam_section(request):
    if not (has_exam_section_access(request.user) or can_manage_module(request.user, None) or request.user.is_authenticated):
        return HttpResponseForbidden("Unauthorized")

    module, module_choices = _selected_exam_module(request)
    if not module:
        messages.error(request, "No exam-access module available.")
        return redirect("/home/")
    can_manage = can_manage_module(request.user, module) or can_manage_exam_module(request.user, module)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action in {
            "create_session",
            "assign_manager",
            "create_faculty_account",
            "save_subject_evaluators",
            "create_entry",
            "create_seating_block",
            "copy_seating_blocks",
            "shift_preview_block",
            "bulk_update_preview_ranges",
            "finalize_all_seating_blocks",
            "assign_block",
            "lock_entry",
            "unlock_entry",
        } and not can_manage:
            return HttpResponseForbidden("Unauthorized")

        if action == "create_session":
            test_name = (request.POST.get("test_name") or "").strip().upper()
            title = (request.POST.get("title") or "").strip()
            if test_name not in {"T1", "T2", "T3", "T4"}:
                messages.error(request, "Select a valid exam.")
            else:
                session, created = ModuleExamSession.objects.get_or_create(
                    module=module,
                    test_name=test_name,
                    defaults={"title": title, "created_by": request.user},
                )
                if not created:
                    session.title = title or session.title
                    session.save(update_fields=["title", "updated_at"])
                    messages.success(request, f"{test_name} exam updated.")
                else:
                    messages.success(request, f"{test_name} exam created.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={test_name}")

        if action == "assign_manager":
            user_id = (request.POST.get("manager_user_id") or "").strip()
            manager = User.objects.filter(id=user_id).first()
            if not manager:
                messages.error(request, "Select a valid exam manager.")
            else:
                ModuleExamManager.objects.get_or_create(module=module, user=manager, defaults={"assigned_by": request.user})
                messages.success(request, f"{manager.username} can now manage exam section for this module.")
            return redirect(f"/exam-section/?module_id={module.id}")

        if action == "create_faculty_account":
            short_code = (request.POST.get("short_code") or "").strip().upper()
            full_name = (request.POST.get("full_name") or "").strip()
            password = (request.POST.get("password") or "").strip()
            email = (request.POST.get("email") or "").strip()
            if not short_code or len(short_code) > 10:
                messages.error(request, "Enter a valid short code.")
            elif not password:
                messages.error(request, "Password is required.")
            elif ExamFacultyProfile.objects.filter(short_code=short_code).exists():
                messages.error(request, "Short code already exists.")
            elif User.objects.filter(username__iexact=short_code.lower()).exists():
                messages.error(request, "Username already exists.")
            else:
                user = User.objects.create_user(username=short_code.lower(), password=password, email=email, is_active=True)
                mentor, _ = Mentor.objects.get_or_create(name=short_code, defaults={"full_name": full_name, "faculty_type": "Faculty"})
                if full_name and mentor.full_name != full_name:
                    mentor.full_name = full_name
                    mentor.save(update_fields=["full_name", "updated_at"])
                ExamFacultyProfile.objects.create(user=user, mentor=mentor, short_code=short_code, full_name=full_name or mentor.full_name)
                messages.success(request, f"Faculty account created. Username: {user.username}")
            redirect_anchor = (request.POST.get("redirect_anchor") or "faculty-directory").strip() or "faculty-directory"
            return redirect(f"/exam-section/?module_id={module.id}#{redirect_anchor}")

        if action == "save_subject_evaluators":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            if not session:
                messages.error(request, "Select a valid exam session.")
                return redirect(f"/exam-section/?module_id={module.id}")
            subject_ids = list(
                module.subjects.filter(is_active=True).values_list("id", flat=True)
            )
            active_profiles = list(ExamFacultyProfile.objects.filter(is_active=True).select_related("user", "mentor"))
            allowed_evaluator_ids = {profile.user_id for profile in active_profiles}
            ExamSubjectEvaluator.objects.filter(session=session).delete()
            creates = []
            validation_failed = False
            for subject_id in subject_ids:
                selected_ids = []
                seen = set()
                for slot in range(1, 6):
                    value = (request.POST.get(f"subject_eval_{subject_id}_{slot}") or "").strip().upper()
                    if not value:
                        continue
                    profile = _resolve_evaluator_profile(value, active_profiles)
                    if not profile:
                        continue
                    evaluator_id = profile.user_id
                    if evaluator_id not in allowed_evaluator_ids or evaluator_id in seen:
                        continue
                    selected_ids.append(evaluator_id)
                    seen.add(evaluator_id)
                if not selected_ids:
                    validation_failed = True
                    break
                for evaluator_id in selected_ids:
                    creates.append(
                        ExamSubjectEvaluator(
                            session=session,
                            subject_id=subject_id,
                            evaluator_id=evaluator_id,
                            assigned_by=request.user,
                        )
                    )
            if validation_failed:
                messages.error(request, "Map at least one evaluator for every subject.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#evaluator-management")
            if creates:
                ExamSubjectEvaluator.objects.bulk_create(creates, ignore_conflicts=True)
            messages.success(request, f"Saved evaluator mapping for {session.test_name}.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#evaluator-management")

        if action == "create_entry":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            subject = Subject.objects.filter(id=request.POST.get("subject_id"), module=module, is_active=True).first()
            if not session or not subject:
                messages.error(request, "Select a valid exam and subject.")
                return redirect(f"/exam-section/?module_id={module.id}")
            defaults = exam_phase_defaults(session.test_name)
            mode = (request.POST.get("entry_mode") or ExamTimetableEntry.MODE_OFFLINE).strip()
            if mode not in {ExamTimetableEntry.MODE_OFFLINE, ExamTimetableEntry.MODE_ONLINE, ExamTimetableEntry.MODE_BOTH}:
                mode = ExamTimetableEntry.MODE_OFFLINE
            try:
                exam_date = datetime.strptime((request.POST.get("exam_date") or "").strip(), "%Y-%m-%d").date()
                start_time = datetime.strptime((request.POST.get("start_time") or "").strip(), "%H:%M").time()
                end_time = datetime.strptime((request.POST.get("end_time") or "").strip(), "%H:%M").time()
                entry_deadline = timezone.make_aware(
                    datetime.strptime((request.POST.get("entry_deadline") or "").strip(), "%Y-%m-%dT%H:%M")
                )
                offline_max = (request.POST.get("offline_max_marks") or "").strip()
                online_max = (request.POST.get("online_max_marks") or "").strip()
                if mode == ExamTimetableEntry.MODE_BOTH:
                    offline_max = offline_max or "16"
                    online_max = online_max or "9"
                    max_marks = request.POST.get("max_marks") or str(Decimal(offline_max) + Decimal(online_max))
                    pass_marks = request.POST.get("pass_marks") or "9"
                    total_pass_marks = request.POST.get("total_pass_marks") or str(defaults["total_pass_marks"])
                elif mode == ExamTimetableEntry.MODE_ONLINE:
                    max_marks = request.POST.get("max_marks") or "100"
                    pass_marks = request.POST.get("pass_marks") or "35"
                    total_pass_marks = request.POST.get("total_pass_marks") or "35"
                    offline_max = "0"
                    online_max = max_marks
                else:
                    max_marks = request.POST.get("max_marks") or str(defaults["max_marks"])
                    pass_marks = request.POST.get("pass_marks") or str(defaults["pass_marks"])
                    total_pass_marks = request.POST.get("total_pass_marks") or str(defaults["total_pass_marks"])
                    offline_max = max_marks
                    online_max = "0"
                entry, _ = ExamTimetableEntry.objects.update_or_create(
                    session=session,
                    subject=subject,
                    defaults={
                        "exam_date": exam_date,
                        "start_time": start_time,
                        "end_time": end_time,
                        "entry_deadline": entry_deadline,
                        "mode": mode,
                        "offline_max_marks": offline_max,
                        "online_max_marks": online_max,
                        "max_marks": max_marks,
                        "pass_marks": pass_marks,
                        "total_pass_marks": total_pass_marks,
                    },
                )
                messages.success(request, f"Exam timetable saved for {subject.name}.")
            except ValueError:
                messages.error(request, "Enter valid exam date, time, and deadline.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}")

        if action == "create_seating_block":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            if not session:
                messages.error(request, "Select a valid exam session.")
                return redirect(f"/exam-section/?module_id={module.id}")
            block_type = (request.POST.get("block_type") or "").strip()
            delivery_mode = (request.POST.get("delivery_mode") or ExamSeatingBlock.MODE_OFFLINE).strip()
            if block_type not in {ExamSeatingBlock.TYPE_ENROLLMENT_RANGE, ExamSeatingBlock.TYPE_MANUAL}:
                messages.error(request, "Select a valid block type.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}")
            if delivery_mode not in {ExamSeatingBlock.MODE_OFFLINE, ExamSeatingBlock.MODE_ONLINE}:
                delivery_mode = ExamSeatingBlock.MODE_OFFLINE
            manual_enrollments = (request.POST.get("manual_enrollments") or "").strip()
            dept_label = (request.POST.get("dept_label") or "").strip()
            block_number = (request.POST.get("block_number") or "").strip()
            block_name = (request.POST.get("block_name") or "").strip()
            if not block_name:
                name_bits = [dept_label or session.module.year_level or "Block"]
                if block_number:
                    name_bits.append(f"Block {block_number}")
                block_name = " ".join(name_bits).strip()
            ExamSeatingBlock.objects.create(
                session=session,
                dept_label=dept_label,
                delivery_mode=delivery_mode,
                block_number=block_number,
                room=(request.POST.get("room") or "").strip(),
                lab=(request.POST.get("lab") or "").strip(),
                block_type=block_type,
                name=block_name or "Block",
                batch="",
                enrollment_start=(request.POST.get("enrollment_start") or "").strip(),
                enrollment_end=(request.POST.get("enrollment_end") or "").strip(),
                manual_enrollments=manual_enrollments,
                is_preview=False,
                created_by=request.user,
            )
            messages.success(request, "Seating block saved.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "auto_generate_blocks":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            if not session:
                messages.error(request, "Select a valid exam session.")
                return redirect(f"/exam-section/?module_id={module.id}")
            delivery_mode = (request.POST.get("delivery_mode") or ExamSeatingBlock.MODE_OFFLINE).strip()
            if delivery_mode not in {ExamSeatingBlock.MODE_OFFLINE, ExamSeatingBlock.MODE_ONLINE}:
                delivery_mode = ExamSeatingBlock.MODE_OFFLINE
            start_number_raw = (request.POST.get("start_block_number") or "1").strip()
            try:
                start_number = int(start_number_raw)
            except Exception:
                start_number = 1
            dept_label = (request.POST.get("dept_label") or "").strip()
            rooms = request.POST.getlist("room_list")
            manual_rooms = (request.POST.get("manual_rooms") or "").strip()
            if manual_rooms:
                rooms.extend([item.strip() for item in manual_rooms.replace("\n", ",").split(",") if item.strip()])
            rooms = [room for room in rooms if room]
            if not rooms:
                messages.error(request, "Select at least one room/lab.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
            capacity = 20 if delivery_mode == ExamSeatingBlock.MODE_OFFLINE else 12
            enrollments = list(
                session.module.students.order_by("enrollment").values_list("enrollment", flat=True)
            )
            if not enrollments:
                messages.error(request, "No students found to generate blocks.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
            chunks = [enrollments[i : i + capacity] for i in range(0, len(enrollments), capacity)]
            ExamSeatingBlock.objects.filter(session=session, delivery_mode=delivery_mode, is_preview=True).delete()
            new_blocks = []
            for idx, chunk in enumerate(chunks):
                block_number = str(start_number + idx)
                room_value = rooms[idx % len(rooms)] if rooms else ""
                block_name = f"{dept_label or session.module.year_level} Block {block_number}".strip()
                new_blocks.append(
                    ExamSeatingBlock(
                        session=session,
                        dept_label=dept_label,
                        delivery_mode=delivery_mode,
                        block_number=block_number,
                        room=room_value if delivery_mode == ExamSeatingBlock.MODE_OFFLINE else "",
                        lab=room_value if delivery_mode == ExamSeatingBlock.MODE_ONLINE else "",
                        block_type=ExamSeatingBlock.TYPE_ENROLLMENT_RANGE,
                        name=block_name,
                        batch="",
                        enrollment_start=chunk[0],
                        enrollment_end=chunk[-1],
                        manual_enrollments="",
                        is_preview=True,
                        created_by=request.user,
                    )
                )
            if new_blocks:
                ExamSeatingBlock.objects.bulk_create(new_blocks)
            messages.success(request, f"Generated {len(new_blocks)} preview blocks.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "shift_preview_block":
            block_id = (request.POST.get("seating_block_id") or "").strip()
            delta_raw = (request.POST.get("delta") or "").strip()
            try:
                delta = int(delta_raw)
            except Exception:
                delta = 0
            block = ExamSeatingBlock.objects.filter(id=block_id, session__module=module, is_preview=True).select_related("session").first()
            if not block or delta not in {-1, 1}:
                messages.error(request, "Preview block not found.")
                return redirect(f"/exam-section/?module_id={module.id}")

            session = block.session
            enrollments = list(
                session.module.students.order_by("enrollment").values_list("enrollment", flat=True)
            )
            if not enrollments:
                messages.error(request, "No students available.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

            def _sort_key(b):
                try:
                    return (0, int(str(b.block_number).strip()))
                except Exception:
                    return (1, str(b.block_number))

            blocks = list(
                ExamSeatingBlock.objects.filter(
                    session=session,
                    is_preview=True,
                    delivery_mode=block.delivery_mode,
                )
            )
            blocks.sort(key=_sort_key)

            index_map = {b.id: idx for idx, b in enumerate(blocks)}
            if block.id not in index_map:
                messages.error(request, "Preview block not found.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

            sizes = []
            prev_end = -1
            for b in blocks:
                start_idx = enrollments.index(b.enrollment_start) if b.enrollment_start in enrollments else prev_end + 1
                if start_idx < prev_end + 1:
                    start_idx = prev_end + 1
                if start_idx >= len(enrollments):
                    start_idx = len(enrollments) - 1
                end_idx = enrollments.index(b.enrollment_end) if b.enrollment_end in enrollments else start_idx
                if end_idx < start_idx:
                    end_idx = start_idx
                size = max(1, end_idx - start_idx + 1)
                sizes.append(size)
                prev_end = start_idx + size - 1

            total = sum(sizes)
            if total < len(enrollments):
                sizes[-1] += len(enrollments) - total
            elif total > len(enrollments):
                diff = total - len(enrollments)
                sizes[-1] = max(1, sizes[-1] - diff)

            idx = index_map[block.id]
            if delta == 1:
                if idx + 1 < len(sizes) and sizes[idx + 1] > 1:
                    sizes[idx] += 1
                    sizes[idx + 1] -= 1
                else:
                    messages.error(request, "Cannot increase this block further.")
                    return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
            else:
                if idx == len(sizes) - 1:
                    if sizes[idx] > 1:
                        sizes[idx] -= 1
                        sizes.append(1)
                    else:
                        messages.error(request, "Cannot reduce this block further.")
                        return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
                else:
                    if sizes[idx] > 1:
                        sizes[idx] -= 1
                        sizes[idx + 1] += 1
                    else:
                        sizes.pop(idx)
                        sizes[idx] += 1
                        blocks.pop(idx)

            cursor = 0
            for b, size in zip(blocks, sizes):
                start = enrollments[cursor]
                end = enrollments[cursor + size - 1]
                b.enrollment_start = start
                b.enrollment_end = end
                b.save(update_fields=["enrollment_start", "enrollment_end"])
                cursor += size

            if len(sizes) > len(blocks):
                max_num = 0
                for b in blocks:
                    try:
                        max_num = max(max_num, int(str(b.block_number).strip()))
                    except Exception:
                        continue
                new_number = str(max_num + 1) if max_num else "1"
                last_start = enrollments[cursor]
                last_end = enrollments[cursor]
                name_bits = [block.dept_label or session.module.year_level or "Block", f"Block {new_number}"]
                ExamSeatingBlock.objects.create(
                    session=session,
                    dept_label=block.dept_label,
                    delivery_mode=block.delivery_mode,
                    block_number=new_number,
                    room=block.room if block.delivery_mode == ExamSeatingBlock.MODE_OFFLINE else "",
                    lab=block.lab if block.delivery_mode == ExamSeatingBlock.MODE_ONLINE else "",
                    block_type=ExamSeatingBlock.TYPE_ENROLLMENT_RANGE,
                    name=" ".join(name_bits).strip(),
                    batch="",
                    enrollment_start=last_start,
                    enrollment_end=last_end,
                    manual_enrollments="",
                    is_preview=True,
                    created_by=request.user,
                )
            messages.success(request, "Preview block updated.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "bulk_update_preview_ranges":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            if not session:
                messages.error(request, "Select a valid exam session.")
                return redirect(f"/exam-section/?module_id={module.id}")
            payload_raw = (request.POST.get("payload") or "").strip()
            remove_raw = (request.POST.get("remove_ids") or "").strip()
            try:
                payload = json.loads(payload_raw) if payload_raw else []
            except json.JSONDecodeError:
                messages.error(request, "Invalid preview payload.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
            try:
                remove_ids = json.loads(remove_raw) if remove_raw else []
            except json.JSONDecodeError:
                remove_ids = []
            preview_blocks = list(ExamSeatingBlock.objects.filter(session=session, is_preview=True))
            preview_by_id = {str(block.id): block for block in preview_blocks}
            enrollments = set(
                session.module.students.order_by("enrollment").values_list("enrollment", flat=True)
            )
            if remove_ids:
                ExamSeatingBlock.objects.filter(
                    session=session,
                    is_preview=True,
                    id__in=[rid for rid in remove_ids if str(rid).isdigit() or isinstance(rid, int)],
                ).delete()
            updates = []
            creates = []
            for item in payload:
                block_id = str(item.get("id") or "")
                start = (item.get("start") or "").strip()
                end = (item.get("end") or "").strip()
                is_new = bool(item.get("is_new"))
                if not start or not end:
                    continue
                if enrollments and (start not in enrollments or end not in enrollments):
                    continue
                if is_new:
                    delivery_mode = (item.get("delivery_mode") or ExamSeatingBlock.MODE_OFFLINE).strip()
                    if delivery_mode not in {ExamSeatingBlock.MODE_OFFLINE, ExamSeatingBlock.MODE_ONLINE}:
                        delivery_mode = ExamSeatingBlock.MODE_OFFLINE
                    block_type = (item.get("block_type") or ExamSeatingBlock.TYPE_ENROLLMENT_RANGE).strip()
                    if block_type not in {ExamSeatingBlock.TYPE_ENROLLMENT_RANGE, ExamSeatingBlock.TYPE_MANUAL}:
                        block_type = ExamSeatingBlock.TYPE_ENROLLMENT_RANGE
                    dept_label = (item.get("dept_label") or "").strip()
                    block_number = (item.get("block_number") or "").strip()
                    room_val = (item.get("room") or "").strip()
                    lab_val = (item.get("lab") or "").strip()
                    manual_enrollments = (item.get("manual_enrollments") or "").strip()
                    name_bits = [dept_label or session.module.year_level or "Block"]
                    if block_number:
                        name_bits.append(f"Block {block_number}")
                    block_name = " ".join(name_bits).strip()
                    creates.append(
                        ExamSeatingBlock(
                            session=session,
                            dept_label=dept_label,
                            delivery_mode=delivery_mode,
                            block_number=block_number,
                            room=room_val if delivery_mode == ExamSeatingBlock.MODE_OFFLINE else "",
                            lab=lab_val if delivery_mode == ExamSeatingBlock.MODE_ONLINE else "",
                            block_type=block_type,
                            name=block_name or "Block",
                            batch="",
                            enrollment_start=start,
                            enrollment_end=end,
                            manual_enrollments=manual_enrollments,
                            is_preview=True,
                            created_by=request.user,
                        )
                    )
                    continue
                block = preview_by_id.get(block_id)
                if not block:
                    continue
                block.enrollment_start = start
                block.enrollment_end = end
                updates.append(block)
            if updates:
                ExamSeatingBlock.objects.bulk_update(updates, ["enrollment_start", "enrollment_end"])
            if creates:
                ExamSeatingBlock.objects.bulk_create(creates)
            if updates or creates:
                messages.success(request, "Preview ranges updated.")
            else:
                messages.info(request, "No preview changes to update.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "update_seating_block":
            block_id = (request.POST.get("seating_block_id") or "").strip()
            block = ExamSeatingBlock.objects.filter(id=block_id, session__module=module).first()
            if not block:
                messages.error(request, "Seating block not found.")
                return redirect(f"/exam-section/?module_id={module.id}")
            block.delivery_mode = (request.POST.get("delivery_mode") or block.delivery_mode).strip()
            if block.delivery_mode not in {ExamSeatingBlock.MODE_OFFLINE, ExamSeatingBlock.MODE_ONLINE}:
                block.delivery_mode = ExamSeatingBlock.MODE_OFFLINE
            block.block_number = (request.POST.get("block_number") or "").strip()
            block.dept_label = (request.POST.get("dept_label") or "").strip()
            block.room = (request.POST.get("room") or "").strip()
            block.lab = (request.POST.get("lab") or "").strip()
            block.block_type = (request.POST.get("block_type") or "").strip()
            if block.block_type not in {ExamSeatingBlock.TYPE_ENROLLMENT_RANGE, ExamSeatingBlock.TYPE_MANUAL}:
                block.block_type = ExamSeatingBlock.TYPE_ENROLLMENT_RANGE
            block.enrollment_start = (request.POST.get("enrollment_start") or "").strip()
            block.enrollment_end = (request.POST.get("enrollment_end") or "").strip()
            block.manual_enrollments = (request.POST.get("manual_enrollments") or "").strip()
            if not block.name:
                name_bits = [block.dept_label or block.session.module.year_level or "Block"]
                if block.block_number:
                    name_bits.append(f"Block {block.block_number}")
                block.name = " ".join(name_bits).strip()
            block.save()
            for entry in ExamTimetableEntry.objects.filter(session=block.session):
                sync_exam_blocks_from_seating(entry)
            messages.success(request, "Seating block updated.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={block.session.test_name}#seating-blocks")

        if action == "finalize_seating_blocks":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            delivery_mode = (request.POST.get("delivery_mode") or "").strip()
            if not session or delivery_mode not in {ExamSeatingBlock.MODE_OFFLINE, ExamSeatingBlock.MODE_ONLINE}:
                messages.error(request, "Select a valid exam and mode.")
                return redirect(f"/exam-section/?module_id={module.id}")
            preview_qs = ExamSeatingBlock.objects.filter(session=session, delivery_mode=delivery_mode, is_preview=True)
            if not preview_qs.exists():
                messages.error(request, "No preview blocks to finalize.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
            ExamSeatingBlock.objects.filter(session=session, delivery_mode=delivery_mode, is_preview=False).delete()
            preview_qs.update(is_preview=False)
            for entry in ExamTimetableEntry.objects.filter(session=session):
                sync_exam_blocks_from_seating(entry)
            messages.success(request, "Seating blocks finalized.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "finalize_all_seating_blocks":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            if not session:
                messages.error(request, "Select a valid exam session.")
                return redirect(f"/exam-section/?module_id={module.id}")
            preview_qs = ExamSeatingBlock.objects.filter(session=session, is_preview=True)
            if not preview_qs.exists():
                messages.error(request, "No preview blocks to finalize.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")
            for mode in preview_qs.values_list("delivery_mode", flat=True).distinct():
                ExamSeatingBlock.objects.filter(session=session, delivery_mode=mode, is_preview=False).delete()
            preview_qs.update(is_preview=False)
            for entry in ExamTimetableEntry.objects.filter(session=session):
                sync_exam_blocks_from_seating(entry)
            messages.success(request, "Offline and online preview blocks finalized.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "discard_seating_preview":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            delivery_mode = (request.POST.get("delivery_mode") or "").strip()
            if not session:
                messages.error(request, "Select a valid exam session.")
                return redirect(f"/exam-section/?module_id={module.id}")
            if delivery_mode in {ExamSeatingBlock.MODE_OFFLINE, ExamSeatingBlock.MODE_ONLINE}:
                ExamSeatingBlock.objects.filter(session=session, delivery_mode=delivery_mode, is_preview=True).delete()
            else:
                ExamSeatingBlock.objects.filter(session=session, is_preview=True).delete()
            messages.success(request, "Preview blocks cleared.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "copy_seating_blocks":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            source_id = (request.POST.get("source_session_id") or "").strip()
            source_session = ModuleExamSession.objects.filter(id=source_id, module=module).first()
            if not session or not source_session:
                messages.error(request, "Select a valid source exam.")
                return redirect(f"/exam-section/?module_id={module.id}")
            copied = 0
            for block in ExamSeatingBlock.objects.filter(session=source_session, is_preview=False):
                ExamSeatingBlock.objects.create(
                    session=session,
                    dept_label=block.dept_label,
                    delivery_mode=block.delivery_mode,
                    block_number=block.block_number,
                    room=block.room,
                    lab=block.lab,
                    block_type=block.block_type,
                    name=block.name,
                    batch=block.batch,
                    enrollment_start=block.enrollment_start,
                    enrollment_end=block.enrollment_end,
                    manual_enrollments=block.manual_enrollments,
                    is_preview=False,
                    created_by=request.user,
                )
                copied += 1
            messages.success(request, f"Copied {copied} seating blocks.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "update_entry":
            entry = ExamTimetableEntry.objects.filter(id=request.POST.get("timetable_entry_id"), session__module=module).first()
            if not entry:
                messages.error(request, "Exam subject entry not found.")
                return redirect(f"/exam-section/?module_id={module.id}")
            defaults = exam_phase_defaults(entry.session.test_name)
            mode = (request.POST.get("entry_mode") or entry.mode).strip()
            if mode not in {ExamTimetableEntry.MODE_OFFLINE, ExamTimetableEntry.MODE_ONLINE, ExamTimetableEntry.MODE_BOTH}:
                mode = entry.mode
            try:
                exam_date = datetime.strptime((request.POST.get("exam_date") or "").strip(), "%Y-%m-%d").date()
                start_time = datetime.strptime((request.POST.get("start_time") or "").strip(), "%H:%M").time()
                end_time = datetime.strptime((request.POST.get("end_time") or "").strip(), "%H:%M").time()
                entry_deadline = timezone.make_aware(
                    datetime.strptime((request.POST.get("entry_deadline") or "").strip(), "%Y-%m-%dT%H:%M")
                )
                offline_max = (request.POST.get("offline_max_marks") or "").strip()
                online_max = (request.POST.get("online_max_marks") or "").strip()
                if mode == ExamTimetableEntry.MODE_BOTH:
                    offline_max = offline_max or "16"
                    online_max = online_max or "9"
                    max_marks = request.POST.get("max_marks") or str(Decimal(offline_max) + Decimal(online_max))
                    pass_marks = request.POST.get("pass_marks") or "9"
                    total_pass_marks = request.POST.get("total_pass_marks") or str(defaults["total_pass_marks"])
                elif mode == ExamTimetableEntry.MODE_ONLINE:
                    max_marks = request.POST.get("max_marks") or "100"
                    pass_marks = request.POST.get("pass_marks") or "35"
                    total_pass_marks = request.POST.get("total_pass_marks") or "35"
                    offline_max = "0"
                    online_max = max_marks
                else:
                    max_marks = request.POST.get("max_marks") or str(defaults["max_marks"])
                    pass_marks = request.POST.get("pass_marks") or str(defaults["pass_marks"])
                    total_pass_marks = request.POST.get("total_pass_marks") or str(defaults["total_pass_marks"])
                    offline_max = max_marks
                    online_max = "0"
                entry.exam_date = exam_date
                entry.start_time = start_time
                entry.end_time = end_time
                entry.entry_deadline = entry_deadline
                entry.mode = mode
                entry.offline_max_marks = offline_max
                entry.online_max_marks = online_max
                entry.max_marks = max_marks
                entry.pass_marks = pass_marks
                entry.total_pass_marks = total_pass_marks
                entry.save()
                messages.success(request, f"Exam timetable updated for {entry.subject.name}.")
            except ValueError:
                messages.error(request, "Enter valid exam date, time, and deadline.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={entry.session.test_name}#entry-{entry.id}")

        if action == "assign_block":
            entry = ExamTimetableEntry.objects.filter(id=request.POST.get("timetable_entry_id"), session__module=module).first()
            evaluator = User.objects.filter(id=request.POST.get("evaluator_user_id")).first()
            seating_block_id = (request.POST.get("seating_block_id") or "").strip()
            if not entry or not evaluator:
                messages.error(request, "Select a valid subject and evaluator.")
                return redirect(f"/exam-section/?module_id={module.id}")
            if not ExamSubjectEvaluator.objects.filter(session=entry.session, subject=entry.subject, evaluator=evaluator).exists():
                messages.error(request, "This evaluator is not mapped to the selected subject.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={entry.session.test_name}#entry-{entry.id}")
            seating_block = ExamSeatingBlock.objects.filter(id=seating_block_id, session=entry.session, is_preview=False).first()
            if not seating_block:
                messages.error(request, "Select a valid seating block.")
                return redirect(f"/exam-section/?module_id={module.id}&test_name={entry.session.test_name}#entry-{entry.id}")
            block = ExamBlock.objects.create(
                timetable_entry=entry,
                evaluator=evaluator,
                delivery_mode=seating_block.delivery_mode,
                block_number=seating_block.block_number,
                room=seating_block.room,
                lab=seating_block.lab,
                block_type=seating_block.block_type,
                name=seating_block.name or f"{entry.subject.short_name or entry.subject.name} Block",
                batch=seating_block.batch,
                enrollment_start=seating_block.enrollment_start,
                enrollment_end=seating_block.enrollment_end,
                created_by=request.user,
            )
            manual_student_ids = [value for value in request.POST.getlist("manual_student_ids") if value.isdigit()]
            manual_enrollments = []
            manual_enrollments = [
                value.strip()
                for value in (seating_block.manual_enrollments or "").replace("\n", ",").split(",")
                if value.strip()
            ]
            if manual_enrollments:
                extra_students = list(
                    entry.session.module.students.filter(enrollment__in=manual_enrollments).values_list("id", flat=True)
                )
                manual_student_ids.extend(extra_students)
            students, skipped = build_block_students(block, manual_student_ids=manual_student_ids)
            if not students:
                block.delete()
                messages.error(request, "No students matched this block.")
            else:
                messages.success(
                    request,
                    f"Block created with {len(students)} students." + (f" {skipped} already belonged to another block." if skipped else ""),
                )
            return redirect(f"/exam-section/?module_id={module.id}&test_name={entry.session.test_name}#entry-{entry.id}")

        if action in {"lock_entry", "unlock_entry"}:
            entry = ExamTimetableEntry.objects.filter(id=request.POST.get("timetable_entry_id"), session__module=module).first()
            if not entry:
                messages.error(request, "Exam subject entry not found.")
                return redirect(f"/exam-section/?module_id={module.id}")
            if action == "unlock_entry":
                entry.is_locked = False
                entry.lock_message = "Unlocked manually by exam manager."
                entry.save(update_fields=["is_locked", "lock_message", "updated_at"])
                messages.success(request, "Marks entry unlocked.")
            else:
                stats = {
                    "total": ExamBlockStudent.objects.filter(block__timetable_entry=entry).count(),
                    "pending": ExamBlockStudent.objects.filter(block__timetable_entry=entry).exclude(
                        student_id__in=ExamMarkEntry.objects.filter(timetable_entry=entry).values_list("student_id", flat=True)
                    ).count(),
                }
                if not stats["total"]:
                    messages.error(request, "Create evaluator blocks before locking.")
                elif stats["pending"]:
                    messages.error(request, "Some students still have pending marks. Lock blocked.")
                else:
                    try:
                        publish_locked_entry(entry, request.user)
                        entry.lock_message = "Locked and published into result flow."
                        entry.save(update_fields=["lock_message", "updated_at"])
                        messages.success(request, "Marks locked and published.")
                    except ValueError as exc:
                        messages.error(request, str(exc))
            return redirect(f"/exam-section/?module_id={module.id}&test_name={entry.session.test_name}#entry-{entry.id}")

    sessions = list(ModuleExamSession.objects.filter(module=module).order_by("test_name"))
    selected_test_name = (request.GET.get("test_name") or "").strip().upper()
    selected_session = None
    if selected_test_name:
        selected_session = ModuleExamSession.objects.filter(module=module, test_name=selected_test_name).first()
    if not selected_session and sessions:
        selected_session = sessions[0]

    mentors, profiles, unregistered_names = _module_faculty_directory(module)
    profile_by_user_id = {profile.user_id: profile for profile in profiles}
    evaluator_search_options = [
        {
            "short_code": profile.short_code,
            "full_name": (profile.full_name or getattr(profile.mentor, "full_name", "") or "").strip(),
            "label": f"{profile.short_code} - {(profile.full_name or getattr(profile.mentor, 'full_name', '') or profile.short_code).strip()}",
        }
        for profile in profiles
    ]
    manager_candidates = _manager_candidate_users(module)
    module_managers = list(ModuleExamManager.objects.filter(module=module).select_related("user").order_by("user__username"))
    students = list(module.students.select_related("mentor").order_by("roll_no", "enrollment"))

    entries = []
    session_subject_evaluator_map = {}
    subject_evaluator_rows = []
    if selected_session:
        entries = list(
            ExamTimetableEntry.objects.filter(session=selected_session)
            .select_related("subject", "published_upload")
            .order_by("exam_date", "start_time", "subject__name")
        )
        selected_subjects = list(module.subjects.filter(is_active=True).order_by("display_order", "name"))
        subject_links = list(
            ExamSubjectEvaluator.objects.filter(session=selected_session, subject__in=selected_subjects)
            .select_related("subject", "evaluator")
            .order_by("subject__display_order", "subject__name", "evaluator__username")
        )
        for link in subject_links:
            session_subject_evaluator_map.setdefault(link.subject_id, []).append(link.evaluator_id)
        for subject in selected_subjects:
            selected_user_ids = [user_id for user_id in session_subject_evaluator_map.get(subject.id, []) if user_id in profile_by_user_id][:5]
            selected_profiles = [profile_by_user_id[user_id] for user_id in selected_user_ids]
            selected_slot_user_ids = [profile_by_user_id[user_id].short_code for user_id in selected_user_ids] + [""] * max(0, 5 - len(selected_user_ids))
            subject_evaluator_rows.append(
                {
                    "subject": subject,
                    "selected_user_ids": set(selected_user_ids),
                    "selected_profiles": selected_profiles,
                    "selected_slot_user_ids": selected_slot_user_ids,
                }
            )
    enrollment_choices = []
    enrollment_branch_map = {}
    available_branch_rows = []
    available_students_total = 0
    required_offline_blocks = 0
    required_online_blocks = 0
    if module:
        module_students_for_summary = list(module.students.order_by("enrollment"))
        enrollment_choices = [student.enrollment for student in module_students_for_summary]
        available_branch_rows, _ = _branch_count_summary(module_students_for_summary, module)
        available_students_total = len(module_students_for_summary)
        required_offline_blocks = ceil(available_students_total / 20) if available_students_total else 0
        required_online_blocks = ceil(available_students_total / 12) if available_students_total else 0
        enrollment_branch_map = {
            student.enrollment: _infer_branch_label(student, module)
            for student in module_students_for_summary
        }
    dept_label_default = ""
    if module and module.variant:
        variant = module.variant.split("-")[0].strip()
        dept_label_default = variant or module.year_level
    elif module:
        dept_label_default = module.year_level
    seating_blocks = []
    seating_block_rows = []
    preview_block_rows = []
    selected_block_view_mode = (request.GET.get("block_view_mode") or "").strip().lower()
    next_block_number = 1
    next_enrollment_start = ""
    next_enrollment_end = ""
    year_rooms = []
    if selected_session:
        def _block_sort_key(item):
            try:
                return (0, int(str(item.block_number).strip()))
            except Exception:
                return (1, str(item.block_number))

        seating_blocks = list(
            ExamSeatingBlock.objects.filter(session=selected_session, is_preview=False)
        )
        seating_blocks.sort(key=_block_sort_key)
        preview_blocks = list(
            ExamSeatingBlock.objects.filter(session=selected_session, is_preview=True)
        )
        preview_blocks.sort(key=_block_sort_key)
        block_numbers = []
        for block in seating_blocks:
            try:
                block_numbers.append(int(str(block.block_number).strip()))
            except Exception:
                continue
        if block_numbers:
            next_block_number = max(block_numbers) + 1
        for block in seating_blocks:
            manual_ids = []
            manual_enrollments = [
                value.strip()
                for value in (block.manual_enrollments or "").replace("\n", ",").split(",")
                if value.strip()
            ]
            if manual_enrollments:
                manual_ids = list(
                    selected_session.module.students.filter(enrollment__in=manual_enrollments).values_list("id", flat=True)
                )
            students = resolve_block_students(
                selected_session.module,
                block.block_type,
                block.batch,
                block.enrollment_start,
                block.enrollment_end,
                manual_student_ids=manual_ids,
            )
            branch_rows, branch_display = _branch_count_summary(students, selected_session.module)
            branch_detail_rows = _branch_detail_rows(students, selected_session.module) or [
                {"branch": "-", "count": 0, "label": "-", "range_display": "-"}
            ]
            seating_block_rows.append(
                {
                    "block": block,
                    "student_count": len(students),
                    "branch_rows": branch_rows,
                    "branch_display": branch_display,
                    "branch_detail_rows": branch_detail_rows,
                    "branch_rowspan": len(branch_detail_rows),
                }
            )
        available_final_modes = sorted({row["block"].delivery_mode for row in seating_block_rows})
        if selected_block_view_mode not in available_final_modes:
            selected_block_view_mode = available_final_modes[0] if available_final_modes else ""
        if selected_block_view_mode:
            seating_block_rows = [
                row for row in seating_block_rows if row["block"].delivery_mode == selected_block_view_mode
            ]
        for block in preview_blocks:
            manual_ids = []
            manual_enrollments = [
                value.strip()
                for value in (block.manual_enrollments or "").replace("\n", ",").split(",")
                if value.strip()
            ]
            if manual_enrollments:
                manual_ids = list(
                    selected_session.module.students.filter(enrollment__in=manual_enrollments).values_list("id", flat=True)
                )
            students = resolve_block_students(
                selected_session.module,
                block.block_type,
                block.batch,
                block.enrollment_start,
                block.enrollment_end,
                manual_student_ids=manual_ids,
            )
            branch_rows, branch_display = _branch_count_summary(students, selected_session.module)
            preview_block_rows.append(
                {
                    "block": block,
                    "student_count": len(students),
                    "branch_rows": branch_rows,
                    "branch_display": branch_display,
                }
            )
        if seating_blocks and enrollment_choices:
            last_end = ""
            for block in reversed(seating_blocks):
                if block.enrollment_end:
                    last_end = block.enrollment_end
                    break
            if last_end and last_end in enrollment_choices:
                idx = enrollment_choices.index(last_end)
                if idx + 1 < len(enrollment_choices):
                    next_enrollment_start = enrollment_choices[idx + 1]
                    next_enrollment_end = enrollment_choices[idx + 1]
        year_modules = AcademicModule.objects.filter(is_active=True)
        if module.year_scope_id:
            year_modules = year_modules.filter(year_scope=module.year_scope)
        else:
            year_modules = year_modules.filter(id=module.id)
        year_rooms = sorted(
            {
                (room or "").strip()
                for room in TimetableEntry.objects.filter(module__in=year_modules, is_active=True)
                .values_list("room", flat=True)
                if (room or "").strip()
            }
        )
    available_subjects = []
    if selected_session:
        available_subjects = list(
            module.subjects.filter(is_active=True).exclude(exam_entries__session=selected_session).order_by("name")
        )
    entry_cards = []
    for entry in entries:
        sync_exam_blocks_from_seating(entry)
        blocks = list(entry.blocks.select_related("evaluator").order_by("name", "id"))
        allowed_profiles = [
            profile_by_user_id[user_id]
            for user_id in session_subject_evaluator_map.get(entry.subject_id, [])
            if user_id in profile_by_user_id
        ]
        block_status_rows = _entry_block_statuses(entry)
        total_students = ExamBlockStudent.objects.filter(block__timetable_entry=entry).count()
        entered_students = ExamMarkEntry.objects.filter(timetable_entry=entry).values("student_id").distinct().count()
        absent_students = ExamMarkEntry.objects.filter(timetable_entry=entry, is_absent=True).count()
        failed_students = ExamMarkEntry.objects.filter(
            timetable_entry=entry,
            is_absent=False,
            marks_obtained__lt=entry.pass_marks,
        ).count()
        completed_blocks = [row for row in block_status_rows if row["is_done"]]
        pending_blocks = [row for row in block_status_rows if not row["is_done"]]
        entry_cards.append(
            {
                "entry": entry,
                "blocks": blocks,
                "allowed_evaluators": allowed_profiles,
                "block_status_rows": block_status_rows,
                "completed_blocks": completed_blocks,
                "pending_blocks": pending_blocks,
                "stats": {
                    "total_students": total_students,
                    "entered_students": entered_students,
                    "absent_students": absent_students,
                    "failed_students": failed_students,
                    "pending_students": max(total_students - entered_students, 0),
                    "completed_blocks": len(completed_blocks),
                    "pending_blocks": len(pending_blocks),
                    "opens_at": entry_opens_at(entry),
                },
            }
        )

    return render(
        request,
        "exam_section.html",
        {
            "module": module,
            "module_choices": module_choices,
            "can_manage_exam": can_manage,
            "sessions": sessions,
            "selected_session": selected_session,
            "entries": entries,
            "entry_cards": entry_cards,
            "profiles": profiles,
            "evaluator_search_options": evaluator_search_options,
            "mentors": mentors,
            "unregistered_names": unregistered_names,
            "manager_candidates": manager_candidates,
            "module_managers": module_managers,
            "subject_evaluator_rows": subject_evaluator_rows,
            "students": students,
            "available_subjects": available_subjects,
            "seating_blocks": seating_blocks,
            "seating_block_rows": seating_block_rows,
            "preview_block_rows": preview_block_rows,
            "selected_block_view_mode": selected_block_view_mode,
            "enrollment_choices": enrollment_choices,
            "dept_label_default": dept_label_default,
            "next_block_number": next_block_number,
            "next_enrollment_start": next_enrollment_start,
            "next_enrollment_end": next_enrollment_end,
            "year_rooms": year_rooms,
            "available_branch_rows": available_branch_rows,
            "available_students_total": available_students_total,
            "required_offline_blocks": required_offline_blocks,
            "required_online_blocks": required_online_blocks,
            "enrollment_branch_map": enrollment_branch_map,
            "phase_defaults": (exam_phase_defaults(selected_session.test_name) if selected_session else {}),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def exam_marks_entry(request, block_id):
    block = get_object_or_404(
        ExamBlock.objects.select_related("timetable_entry", "timetable_entry__session", "timetable_entry__subject", "evaluator"),
        id=block_id,
    )
    can_manage = can_manage_module(request.user, block.timetable_entry.session.module) or can_manage_exam_module(
        request.user,
        block.timetable_entry.session.module,
    )
    if not can_enter_exam_block(request.user, block) and not can_manage:
        return HttpResponseForbidden("Unauthorized")

    editable = can_enter_exam_block(request.user, block)
    can_edit_now, edit_message = can_edit_entry_now(block.timetable_entry)
    if ExamSeatingBlock.objects.filter(session=block.timetable_entry.session, is_preview=False).exists():
        sync_exam_blocks_from_seating(block.timetable_entry)
    block = get_object_or_404(
        ExamBlock.objects.select_related("timetable_entry", "timetable_entry__session", "timetable_entry__subject", "evaluator"),
        id=block_id,
    )
    if request.method == "POST":
        if not editable:
            return HttpResponseForbidden("Unauthorized")
        if not can_edit_now:
            messages.error(request, edit_message)
            return redirect(f"/exam-section/marks/{block.id}/")
        entry = block.timetable_entry
        for link in block.student_links.select_related("student").order_by("student__roll_no", "student__name"):
            if entry.mode == ExamTimetableEntry.MODE_BOTH:
                raw_offline = request.POST.get(f"offline_mark_{link.student_id}", "")
                raw_online = request.POST.get(f"online_mark_{link.student_id}", "")
                if not (raw_offline or "").strip() and not (raw_online or "").strip():
                    continue
                off_text = (raw_offline or "").strip().upper()
                on_text = (raw_online or "").strip().upper()
                if "AB" in {off_text, on_text}:
                    if (off_text and off_text != "AB") or (on_text and on_text != "AB"):
                        messages.error(request, f"{link.student.enrollment}: Use AB only if absent.")
                        return redirect(f"/exam-section/marks/{block.id}/")
                    ExamMarkEntry.objects.update_or_create(
                        timetable_entry=entry,
                        block=block,
                        student=link.student,
                        defaults={
                            "evaluator": request.user,
                            "raw_value": "AB",
                            "raw_offline": "AB" if off_text == "AB" else "",
                            "raw_online": "AB" if on_text == "AB" else "",
                            "marks_obtained": None,
                            "offline_marks": None,
                            "online_marks": None,
                            "is_absent": True,
                        },
                    )
                    continue
                if not off_text or not on_text:
                    messages.error(request, f"{link.student.enrollment}: Enter both offline and online marks (or AB).")
                    return redirect(f"/exam-section/marks/{block.id}/")
                try:
                    raw_off_text, offline_marks, _ = parse_exam_mark(off_text, entry.offline_max_marks)
                    raw_on_text, online_marks, _ = parse_exam_mark(on_text, entry.online_max_marks)
                except ValueError as exc:
                    messages.error(request, f"{link.student.enrollment}: {exc}")
                    return redirect(f"/exam-section/marks/{block.id}/")
                total = (offline_marks or Decimal("0")) + (online_marks or Decimal("0"))
                if total > Decimal(str(entry.max_marks)):
                    messages.error(request, f"{link.student.enrollment}: Total cannot exceed {entry.max_marks}.")
                    return redirect(f"/exam-section/marks/{block.id}/")
                ExamMarkEntry.objects.update_or_create(
                    timetable_entry=entry,
                    block=block,
                    student=link.student,
                    defaults={
                        "evaluator": request.user,
                        "raw_value": str(total),
                        "raw_offline": raw_off_text or "",
                        "raw_online": raw_on_text or "",
                        "marks_obtained": total,
                        "offline_marks": offline_marks,
                        "online_marks": online_marks,
                        "is_absent": False,
                    },
                )
                continue

            raw_value = request.POST.get(f"mark_{link.student_id}", "")
            if not (raw_value or "").strip():
                continue
            try:
                raw_text, numeric_value, is_absent = parse_exam_mark(raw_value, entry.max_marks)
            except ValueError as exc:
                messages.error(request, f"{link.student.enrollment}: {exc}")
                return redirect(f"/exam-section/marks/{block.id}/")
            ExamMarkEntry.objects.update_or_create(
                timetable_entry=entry,
                block=block,
                student=link.student,
                defaults={
                    "evaluator": request.user,
                    "raw_value": raw_text or "",
                    "marks_obtained": numeric_value,
                    "offline_marks": None,
                    "online_marks": None,
                    "raw_offline": "",
                    "raw_online": "",
                    "is_absent": is_absent,
                },
            )
        block_stats = exam_stats_for_block(block)
        if block_stats["total"] and block_stats["pending"] == 0:
            messages.success(request, f"Block no. {block.block_number or block.id} marks entry done.")
        else:
            messages.success(request, "Marks saved.")
        return redirect(f"/exam-section/marks/{block.id}/")

    student_links = list(block.student_links.select_related("student", "student__mentor").order_by("student__roll_no", "student__name"))
    marks_map = {
        row.student_id: row
        for row in ExamMarkEntry.objects.filter(block=block).select_related("student")
    }
    compiled_rows_map = {row["enrollment"]: row for row in compiled_rows_for_entry(block.timetable_entry)}
    mark_rows = [
        {"link": link, "mark": marks_map.get(link.student_id), "compiled": compiled_rows_map.get(link.student.enrollment, {})}
        for link in student_links
    ]
    stats = exam_stats_for_block(block)
    entry_header = _entry_compiled_header(block.timetable_entry, block.timetable_entry.session.module)
    return render(
        request,
        "exam_marks_entry.html",
        {
            "block": block,
            "mark_rows": mark_rows,
            "entry": block.timetable_entry,
            "entry_header": entry_header,
            "editable": editable and can_edit_now,
            "edit_message": "" if editable and can_edit_now else edit_message,
            "stats": stats,
        },
    )


@login_required
@require_http_methods(["GET"])
def exam_compiled_export(request, entry_id, export_format):
    entry = get_object_or_404(
        ExamTimetableEntry.objects.select_related("session", "session__module", "subject"),
        id=entry_id,
    )
    if not (can_manage_module(request.user, entry.session.module) or can_manage_exam_module(request.user, entry.session.module)):
        return HttpResponseForbidden("Unauthorized")
    if export_format == "excel":
        return _render_entry_compiled_excel(entry)
    if export_format == "pdf":
        return _render_entry_compiled_pdf(entry)
    return HttpResponseForbidden("Invalid export format")
