from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access import can_manage_module, modules_for_user
from .exam_access import can_enter_exam_block, can_manage_exam_module, exam_modules_for_user, has_exam_section_access
from .exam_services import (
    build_block_students,
    can_edit_entry_now,
    entry_opens_at,
    exam_phase_defaults,
    exam_stats_for_block,
    parse_exam_mark,
    publish_locked_entry,
    resolve_block_students,
)
from .models import (
    AcademicModule,
    CoordinatorModuleAccess,
    ExamBlock,
    ExamBlockStudent,
    ExamSeatingBlock,
    ExamFacultyProfile,
    ExamMarkEntry,
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
    year_modules = AcademicModule.objects.filter(is_active=True)
    if module.year_scope_id:
        year_modules = year_modules.filter(year_scope=module.year_scope)
    else:
        year_modules = year_modules.filter(id=module.id)
    faculty_names = sorted(
        {
            (name or "").strip().upper()
            for name in TimetableEntry.objects.filter(module__in=year_modules, is_active=True).values_list("faculty", flat=True)
            if (name or "").strip()
        }
    )
    mentors = list(
        Mentor.objects.filter(
            Q(name__in=faculty_names)
            | Q(student__module__in=year_modules)
            | Q(module_accesses__module__in=year_modules)
        )
        .distinct()
        .order_by("name")
    )
    profiles = list(
        ExamFacultyProfile.objects.filter(Q(mentor__in=mentors) | Q(short_code__in=faculty_names))
        .select_related("user", "mentor")
        .order_by("short_code")
    )
    profile_codes = {profile.short_code for profile in profiles}
    unregistered_names = [name for name in faculty_names if name not in profile_codes]
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
            "create_entry",
            "create_seating_block",
            "copy_seating_blocks",
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
            return redirect(f"/exam-section/?module_id={module.id}#faculty-directory")

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
                created_by=request.user,
            )
            messages.success(request, "Seating block saved.")
            return redirect(f"/exam-section/?module_id={module.id}&test_name={session.test_name}#seating-blocks")

        if action == "copy_seating_blocks":
            session = ModuleExamSession.objects.filter(id=request.POST.get("session_id"), module=module).first()
            source_id = (request.POST.get("source_session_id") or "").strip()
            source_session = ModuleExamSession.objects.filter(id=source_id, module=module).first()
            if not session or not source_session:
                messages.error(request, "Select a valid source exam.")
                return redirect(f"/exam-section/?module_id={module.id}")
            copied = 0
            for block in ExamSeatingBlock.objects.filter(session=source_session):
                ExamSeatingBlock.objects.create(
                    session=session,
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
            seating_block = ExamSeatingBlock.objects.filter(id=seating_block_id, session=entry.session).first()
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

    entries = []
    if selected_session:
        entries = list(
            ExamTimetableEntry.objects.filter(session=selected_session)
            .select_related("subject", "published_upload")
            .order_by("exam_date", "start_time", "subject__name")
        )
    enrollment_choices = []
    if module:
        enrollment_choices = list(
            module.students.order_by("enrollment").values_list("enrollment", flat=True).distinct()
        )
    dept_label_default = ""
    if module and module.variant:
        variant = module.variant.split("-")[0].strip()
        dept_label_default = variant or module.year_level
    elif module:
        dept_label_default = module.year_level
    seating_blocks = []
    seating_block_rows = []
    next_block_number = 1
    next_enrollment_start = ""
    next_enrollment_end = ""
    if selected_session:
        seating_blocks = list(ExamSeatingBlock.objects.filter(session=selected_session).order_by("name", "id"))
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
            seating_block_rows.append({"block": block, "student_count": len(students)})
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
    mentors, profiles, unregistered_names = _module_faculty_directory(module)
    manager_candidates = _manager_candidate_users(module)
    module_managers = list(ModuleExamManager.objects.filter(module=module).select_related("user").order_by("user__username"))
    students = list(module.students.select_related("mentor").order_by("roll_no", "enrollment"))
    available_subjects = []
    if selected_session:
        available_subjects = list(
            module.subjects.filter(is_active=True).exclude(exam_entries__session=selected_session).order_by("name")
        )
    entry_cards = []
    for entry in entries:
        blocks = list(entry.blocks.select_related("evaluator").order_by("name", "id"))
        total_students = ExamBlockStudent.objects.filter(block__timetable_entry=entry).count()
        entered_students = ExamMarkEntry.objects.filter(timetable_entry=entry).values("student_id").distinct().count()
        absent_students = ExamMarkEntry.objects.filter(timetable_entry=entry, is_absent=True).count()
        failed_students = ExamMarkEntry.objects.filter(
            timetable_entry=entry,
            is_absent=False,
            marks_obtained__lt=entry.pass_marks,
        ).count()
        entry_cards.append(
            {
                "entry": entry,
                "blocks": blocks,
                "stats": {
                    "total_students": total_students,
                    "entered_students": entered_students,
                    "absent_students": absent_students,
                    "failed_students": failed_students,
                    "pending_students": max(total_students - entered_students, 0),
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
            "mentors": mentors,
            "unregistered_names": unregistered_names,
            "manager_candidates": manager_candidates,
            "module_managers": module_managers,
            "students": students,
            "available_subjects": available_subjects,
            "seating_blocks": seating_blocks,
            "seating_block_rows": seating_block_rows,
            "enrollment_choices": enrollment_choices,
            "dept_label_default": dept_label_default,
            "next_block_number": next_block_number,
            "next_enrollment_start": next_enrollment_start,
            "next_enrollment_end": next_enrollment_end,
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
        messages.success(request, "Marks saved.")
        return redirect(f"/exam-section/marks/{block.id}/")

    student_links = list(block.student_links.select_related("student", "student__mentor").order_by("student__roll_no", "student__name"))
    marks_map = {
        row.student_id: row
        for row in ExamMarkEntry.objects.filter(block=block).select_related("student")
    }
    mark_rows = [{"link": link, "mark": marks_map.get(link.student_id)} for link in student_links]
    stats = exam_stats_for_block(block)
    return render(
        request,
        "exam_marks_entry.html",
        {
            "block": block,
            "mark_rows": mark_rows,
            "entry": block.timetable_entry,
            "editable": editable and can_edit_now,
            "edit_message": "" if editable and can_edit_now else edit_message,
            "stats": stats,
        },
    )
