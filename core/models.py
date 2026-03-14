from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password, check_password


class AcademicModule(models.Model):
    YEAR_CHOICES = [
        ("FY", "FY"),
        ("SY", "SY"),
        ("TY", "TY"),
        ("LY", "LY"),
    ]
    VARIANT_CHOICES = [
        ("FY1", "FY1"),
        ("FY2-CE", "FY2-CE"),
        ("FY2-Non CE", "FY2-Non CE"),
        ("FY3", "FY3"),
        ("FY4", "FY4"),
        ("FY5", "FY5"),
        ("SY1", "SY1"),
        ("SY2", "SY2"),
        ("TY1", "TY1"),
        ("TY2", "TY2"),
        ("LY1", "LY1"),
        ("LY2", "LY2"),
    ]
    SEM_CHOICES = [
        ("Sem-1", "Sem-1"),
        ("Sem-2", "Sem-2"),
    ]

    name = models.CharField(max_length=120, unique=True)
    academic_batch = models.CharField(max_length=20)
    year_level = models.CharField(max_length=10, choices=YEAR_CHOICES, default="FY")
    variant = models.CharField(max_length=20, choices=VARIANT_CHOICES, default="FY2-CE")
    semester = models.CharField(max_length=10, choices=SEM_CHOICES, default="Sem-1")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name


# ------------------ MENTOR ------------------
class Mentor(models.Model):
    name = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=100, blank=True, db_index=True)

    def __str__(self):
        return self.name


# ------------------ STUDENT MASTER ------------------
class Student(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="students")
    enrollment = models.CharField(max_length=20)
    roll_no = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=100)
    batch = models.CharField(max_length=20, blank=True)
    division = models.CharField(max_length=20, blank=True)
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE)
    student_mobile = models.CharField(max_length=15, blank=True)
    father_mobile = models.CharField(max_length=15, blank=True)
    mother_mobile = models.CharField(max_length=15, blank=True)
    student_mobile_updated_by_mentor = models.BooleanField(default=False)
    father_mobile_updated_by_mentor = models.BooleanField(default=False)

    class Meta:
        unique_together = ("module", "enrollment")

    def __str__(self):
        return f"{self.name} - {self.enrollment}"


# ------------------ WEEKLY ATTENDANCE ------------------
class Attendance(models.Model):
    week_no = models.IntegerField()
    student = models.ForeignKey(Student, on_delete=models.CASCADE)

    week_percentage = models.FloatField()
    overall_percentage = models.FloatField()

    call_required = models.BooleanField(default=False)

    class Meta:
        unique_together = ('week_no', 'student')

    def __str__(self):
        return f"{self.student.name} - Week {self.week_no}"

class AttendanceWeekMeta(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_AUTO = "auto"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual Upload"),
        (SOURCE_AUTO, "Auto from Daily Attendance"),
    ]

    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="attendance_week_meta")
    week_no = models.IntegerField()
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("module", "week_no")
        ordering = ["-week_no"]

    def __str__(self):
        return f"{self.module.name} Week {self.week_no} ({self.source})"

class AcademicCalendar(models.Model):
    module = models.OneToOneField(AcademicModule, on_delete=models.CASCADE, related_name="attendance_calendar")
    is_active = models.BooleanField(default=False)
    t1_start = models.DateField(null=True, blank=True)
    t1_end = models.DateField(null=True, blank=True)
    t2_start = models.DateField(null=True, blank=True)
    t2_end = models.DateField(null=True, blank=True)
    t3_start = models.DateField(null=True, blank=True)
    t3_end = models.DateField(null=True, blank=True)
    t4_start = models.DateField(null=True, blank=True)
    t4_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Academic Calendar ({self.module.name})"


class AcademicHoliday(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="attendance_holidays")
    date = models.DateField()
    label = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("module", "date")
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.module.name} - {self.date:%Y-%m-%d}"


class SubjectAlias(models.Model):
    module = models.ForeignKey(
        AcademicModule, on_delete=models.CASCADE, null=True, blank=True, related_name="subject_aliases"
    )
    alias = models.CharField(max_length=120)
    canonical = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias"]
        unique_together = ("module", "alias")

    def __str__(self):
        scope = self.module.name if self.module else "All Modules"
        return f"{scope}: {self.alias} -> {self.canonical}"


class TimetableUpload(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="timetable_uploads")
    uploaded_by = models.CharField(max_length=120, blank=True)
    source_name = models.CharField(max_length=255, blank=True)
    rows_total = models.IntegerField(default=0)
    rows_created = models.IntegerField(default=0)
    rows_skipped = models.IntegerField(default=0)
    is_active = models.BooleanField(default=False)
    effective_from = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"Timetable Upload {self.uploaded_at:%Y-%m-%d %H:%M}"


class TimetableEntry(models.Model):
    DAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="timetable_entries")
    upload = models.ForeignKey(
        TimetableUpload, on_delete=models.SET_NULL, null=True, blank=True, related_name="entries"
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    lecture_no = models.IntegerField()
    time_slot = models.CharField(max_length=60, blank=True)
    batch = models.CharField(max_length=30)
    subject = models.CharField(max_length=120, blank=True)
    faculty = models.CharField(max_length=50, blank=True)
    room = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("module", "day_of_week", "lecture_no", "batch", "upload")
        ordering = ["day_of_week", "lecture_no", "batch"]

    def __str__(self):
        return f"{self.batch} - {self.subject} ({self.get_day_of_week_display()})"


class LectureSession(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="lecture_sessions")
    timetable_entry = models.ForeignKey(TimetableEntry, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    day_of_week = models.IntegerField()
    lecture_no = models.IntegerField()
    time_slot = models.CharField(max_length=60, blank=True)
    batch = models.CharField(max_length=30)
    subject = models.CharField(max_length=120, blank=True)
    faculty = models.CharField(max_length=50, blank=True)
    room = models.CharField(max_length=50, blank=True)
    marked_by = models.ForeignKey(Mentor, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("module", "date", "lecture_no", "batch")
        ordering = ["-date", "lecture_no", "batch"]

    def __str__(self):
        return f"{self.batch} - {self.subject} ({self.date:%Y-%m-%d})"


class LectureAbsence(models.Model):
    session = models.ForeignKey(LectureSession, on_delete=models.CASCADE, related_name="absences")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="lecture_absences")
    marked_by = models.ForeignKey(Mentor, on_delete=models.SET_NULL, null=True, blank=True)
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("session", "student")
        ordering = ["session_id", "student__roll_no"]

    def __str__(self):
        return f"{self.session} - {self.student.roll_no}"


class Room(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("module", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.module.name} - {self.name}"


class LectureAdjustment(models.Model):
    TYPE_PROXY = "proxy"
    TYPE_SWAP = "swap"
    TYPE_CHOICES = [
        (TYPE_PROXY, "Proxy"),
        (TYPE_SWAP, "Swap"),
    ]
    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="lecture_adjustments")
    timetable_entry = models.ForeignKey(TimetableEntry, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    batch = models.CharField(max_length=30)
    lecture_no = models.IntegerField()
    time_slot = models.CharField(max_length=60, blank=True)
    subject = models.CharField(max_length=120, blank=True)
    original_faculty = models.CharField(max_length=50, blank=True)
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_PROXY)
    proxy_faculty = models.ForeignKey(Mentor, on_delete=models.SET_NULL, null=True, blank=True, related_name="proxy_adjustments")
    room = models.CharField(max_length=50, blank=True)
    merge_room = models.CharField(max_length=50, blank=True)
    swap_pair_key = models.CharField(max_length=40, blank=True, db_index=True)
    swap_batch = models.CharField(max_length=30, blank=True)
    swap_lecture_no = models.IntegerField(null=True, blank=True)
    swap_time_slot = models.CharField(max_length=60, blank=True)
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_by = models.ForeignKey(Mentor, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_adjustments")
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_by = models.CharField(max_length=120, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "lecture_no", "batch"]

    def __str__(self):
        return f"{self.batch} Lec {self.lecture_no} {self.date:%Y-%m-%d}"



# ------------------ CALL RECORD ------------------
class CallRecord(models.Model):

    STATUS_CHOICES = [
        ('received', 'Received'),
        ('not_received', 'Not Received'),
    ]

    TALKED_CHOICES = [
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('guardian', 'Guardian'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    week_no = models.IntegerField()

    attempt1_time = models.DateTimeField(null=True, blank=True)
    attempt2_time = models.DateTimeField(null=True, blank=True)

    final_status = models.CharField(max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
    talked_with = models.CharField(max_length=20, choices=TALKED_CHOICES, null=True, blank=True)

    duration = models.CharField(max_length=10, blank=True)
    parent_reason = models.TextField(blank=True)

    message_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "week_no"], name="core_call_s_week_idx"),
            models.Index(fields=["week_no", "student"], name="core_call_w_student_idx"),
        ]

    def __str__(self):
        return f"{self.student.name} - Week {self.week_no}"

# ------------------ LOCK WEEK ------------------

class WeekLock(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="week_locks")
    week_no = models.IntegerField()
    locked = models.BooleanField(default=False)

    class Meta:
        unique_together = ("module", "week_no")

    def __str__(self):
        return f"Week {self.week_no} Locked={self.locked}"


class MentorAuthToken(models.Model):
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name="auth_tokens")
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["token"]),
            models.Index(fields=["mentor", "is_active"]),
        ]

    def __str__(self):
        return f"{self.mentor.name} token"

    def is_valid(self):
        return self.is_active and self.expires_at > timezone.now()


TEST_CHOICES = [
    ("T1", "T1"),
    ("T2", "T2"),
    ("T3", "T3"),
    ("T4", "T4"),
    ("REMEDIAL", "REMEDIAL"),
]


class Subject(models.Model):
    FORMAT_FULL = "FULL"
    FORMAT_T4_ONLY = "T4_ONLY"
    FORMAT_CHOICES = [
        (FORMAT_FULL, "T1/T2/T3/T4"),
        (FORMAT_T4_ONLY, "Only T4"),
    ]

    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="subjects")
    source_template = models.ForeignKey(
        "SubjectTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="module_subjects",
    )
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=30, blank=True)
    display_order = models.IntegerField(default=0)
    has_theory = models.BooleanField(default=True)
    has_practical = models.BooleanField(default=True)
    result_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default=FORMAT_FULL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("module", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubjectTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    short_name = models.CharField(max_length=30, blank=True)
    has_theory = models.BooleanField(default=True)
    has_practical = models.BooleanField(default=True)
    result_format = models.CharField(max_length=20, choices=Subject.FORMAT_CHOICES, default=Subject.FORMAT_FULL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MentorPassword(models.Model):
    mentor = models.OneToOneField(Mentor, on_delete=models.CASCADE, related_name="password_credential")
    password_hash = models.CharField(max_length=256)
    updated_at = models.DateTimeField(auto_now=True)

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)

    def __str__(self):
        return f"MentorPassword({self.mentor.name})"


class CoordinatorModuleAccess(models.Model):
    coordinator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="module_accesses")
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="coordinator_accesses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("coordinator", "module")
        ordering = ["coordinator__username", "module__name"]

    def __str__(self):
        return f"{self.coordinator.username} -> {self.module.name}"


class PracticalMarkUpload(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="practical_mark_uploads")
    uploaded_by = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(auto_now=True)
    rows_total = models.IntegerField(default=0)
    rows_matched = models.IntegerField(default=0)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Practical Upload {self.uploaded_at:%Y-%m-%d %H:%M}"


class StudentPracticalMark(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="student_practical_marks")
    upload = models.ForeignKey(PracticalMarkUpload, on_delete=models.CASCADE, related_name="rows")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="practical_marks")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="practical_marks")
    pr_marks = models.FloatField(null=True, blank=True)
    attendance_percentage = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("module", "student", "subject")
        ordering = ["student__roll_no", "student__name", "subject__name"]

    def __str__(self):
        return f"{self.student.enrollment} - {self.subject.name}"


class SifMarksLock(models.Model):
    module = models.OneToOneField(AcademicModule, on_delete=models.CASCADE, related_name="sif_marks_lock")
    locked = models.BooleanField(default=False)
    locked_by = models.CharField(max_length=100, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"SIF Marks Lock ({self.module.name}) = {self.locked}"


class ResultUpload(models.Model):
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="result_uploads")
    test_name = models.CharField(max_length=20, choices=TEST_CHOICES)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="uploads")
    uploaded_by = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(auto_now=True)
    rows_total = models.IntegerField(default=0)
    rows_matched = models.IntegerField(default=0)
    rows_failed = models.IntegerField(default=0)

    class Meta:
        unique_together = ("module", "test_name", "subject")
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.test_name} - {self.subject.name}"


class StudentResult(models.Model):
    upload = models.ForeignKey(ResultUpload, on_delete=models.CASCADE, related_name="results")
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    enrollment = models.CharField(max_length=20)

    marks_current = models.FloatField(null=True, blank=True)
    marks_t1 = models.FloatField(null=True, blank=True)
    marks_t2 = models.FloatField(null=True, blank=True)
    marks_t3 = models.FloatField(null=True, blank=True)
    marks_t4 = models.FloatField(null=True, blank=True)
    marks_total = models.FloatField(null=True, blank=True)

    is_absent = models.BooleanField(default=False)
    fail_flag = models.BooleanField(default=False)
    fail_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("upload", "student")

    def __str__(self):
        return f"{self.upload} - {self.student.enrollment}"


class ResultCallRecord(models.Model):
    STATUS_CHOICES = [
        ("received", "Received"),
        ("not_received", "Not Received"),
    ]

    TALKED_CHOICES = [
        ("father", "Father"),
        ("mother", "Mother"),
        ("guardian", "Guardian"),
    ]

    upload = models.ForeignKey(ResultUpload, on_delete=models.CASCADE, related_name="calls")
    student = models.ForeignKey(Student, on_delete=models.CASCADE)

    attempt1_time = models.DateTimeField(null=True, blank=True)
    attempt2_time = models.DateTimeField(null=True, blank=True)

    final_status = models.CharField(max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
    talked_with = models.CharField(max_length=20, choices=TALKED_CHOICES, null=True, blank=True)

    duration = models.CharField(max_length=10, blank=True)
    parent_reason = models.TextField(blank=True)
    message_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    fail_reason = models.CharField(max_length=255, blank=True)
    marks_current = models.FloatField(default=0)
    marks_total = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["student__roll_no", "student__name"]
        indexes = [
            models.Index(fields=["upload", "student"], name="core_rcall_u_student_idx"),
            models.Index(fields=["student", "upload"], name="core_rcall_s_upload_idx"),
        ]

    def __str__(self):
        return f"{self.upload} - {self.student.enrollment}"


class OtherCallRecord(models.Model):
    STATUS_CHOICES = [
        ("received", "Received"),
        ("not_received", "Not Received"),
    ]

    TALKED_CHOICES = [
        ("father", "Father"),
        ("mother", "Mother"),
        ("guardian", "Guardian"),
        ("student", "Student"),
    ]

    TARGET_CHOICES = [
        ("student", "Student"),
        ("father", "Father"),
    ]
    CATEGORY_CHOICES = [
        ("less_attendance", "Less Attendance"),
        ("poor_result", "Poor Result"),
        ("mentor_intro", "Mentor Intro Call"),
        ("other", "Other"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="other_calls")
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name="other_calls")

    last_called_target = models.CharField(max_length=20, choices=TARGET_CHOICES, blank=True)
    attempt1_time = models.DateTimeField(null=True, blank=True)
    attempt2_time = models.DateTimeField(null=True, blank=True)

    final_status = models.CharField(max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
    talked_with = models.CharField(max_length=20, choices=TALKED_CHOICES, null=True, blank=True)
    call_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    duration = models.CharField(max_length=10, blank=True)
    parent_remark = models.TextField(blank=True)
    call_done_reason = models.TextField(blank=True)
    exam_name = models.CharField(max_length=50, blank=True)
    subject_name = models.CharField(max_length=120, blank=True)
    marks_obtained = models.FloatField(null=True, blank=True)
    marks_out_of = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__roll_no", "student__name"]

    def __str__(self):
        return f"Other Call - {self.student.enrollment}"


class ResultUploadJob(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    job_id = models.CharField(max_length=64, unique=True, db_index=True)
    module = models.ForeignKey(AcademicModule, on_delete=models.CASCADE, related_name="result_upload_jobs")
    created_by = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    message = models.TextField(blank=True)
    progress_current = models.IntegerField(default=0)
    progress_total = models.IntegerField(default=0)
    current_enrollment = models.CharField(max_length=32, blank=True)
    current_student_name = models.CharField(max_length=150, blank=True)
    cancel_requested = models.BooleanField(default=False)
    result_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"ResultUploadJob {self.job_id} ({self.status})"
