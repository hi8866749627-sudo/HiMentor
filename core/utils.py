import pandas as pd
from datetime import datetime
from .models import Mentor, Student, MentorModuleAccess, AcademicModule


# ---------------- PHONE FORMAT ----------------
def format_phone(num):
    """
    Convert any phone format into WhatsApp usable format:
    9876543210 -> 919876543210
    +91 98765-43210 -> 919876543210
    """

    if num is None:
        return ""

    num = str(num).strip()

    if num.lower() == "nan":
        return ""

    # remove decimals
    if num.endswith(".0"):
        num = num[:-2]

    # remove symbols
    for ch in [" ", "-", "+", "(", ")", "."]:
        num = num.replace(ch, "")

    # remove country code if already exists
    if num.startswith("91") and len(num) > 10:
        num = num[-10:]
    if num.startswith("0091") and len(num) > 10:
        num = num[-10:]
    if num.startswith("+91") and len(num) > 10:
        num = num[-10:]

    # add country code
    if len(num) == 10:
        num = "+91" + num

    return num


# ---------------- CLEAN NUMBER ----------------
def clean_number(value):
    """Convert excel numeric to clean string (remove .0, nan, scientific notation)"""

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.lower() == "nan":
        return ""

    # remove .0
    if value.endswith(".0"):
        value = value[:-2]

    # scientific notation
    if "e+" in value.lower():
        try:
            value = "{:.0f}".format(float(value))
        except:
            pass

    return value


def safe_int(value):
    value = clean_number(value)
    if not value:
        return None
    try:
        return int(value)
    except Exception:
        return None


def safe_text(value, max_len):
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    return text[:max_len]


def _normalize_faculty_type(raw):
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    if "hod" in raw:
        return "HoD"
    if "admin" in raw or "administrative" in raw or "non" in raw:
        return "Administrative Staff"
    if "peon" in raw or "helper" in raw:
        return "Peon"
    return "Faculty"


def _normalize_status(raw):
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    if "resign" in raw or "left" in raw:
        return "Resigned"
    if "not" in raw and "work" in raw:
        return "Not Working"
    return "Working"


def _parse_date(val):
    if val in (None, "", "nan"):
        return None
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def _normalize_name_tokens(name):
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in str(name or ""))
    tokens = [t for t in cleaned.split() if t]
    return tokens


def _names_equivalent(a, b):
    if not a or not b:
        return False
    a_tokens = _normalize_name_tokens(a)
    b_tokens = _normalize_name_tokens(b)
    if not a_tokens or not b_tokens:
        return False
    return set(a_tokens) == set(b_tokens) or set(a_tokens).issubset(set(b_tokens)) or set(b_tokens).issubset(set(a_tokens))


def _modules_for_department(dept_key):
    if not dept_key:
        return []
    dept_key = dept_key.upper()
    if dept_key in {"FY", "SY", "TY", "LY"}:
        return list(AcademicModule.objects.filter(year_level__iexact=dept_key, is_active=True))
    if dept_key.startswith(("FY", "SY", "TY", "LY")):
        return list(
            AcademicModule.objects.filter(
                is_active=True,
                variant__istartswith=dept_key,
            )
        )
    return list(AcademicModule.objects.filter(is_active=True, name__icontains=dept_key))


def _read_faculty_excel(file):
    df = pd.read_excel(file)
    if not df.empty:
        return df
    return df


def import_faculty_from_excel(file):
    df = _read_faculty_excel(file)
    if df.empty:
        return 0, 0, 0, [], {}

    added = updated = skipped = 0
    skipped_rows = []

    def _norm_key(val):
        return "".join(ch for ch in str(val or "").lower() if ch.isalnum())

    def col_match(options):
        for col in df.columns:
            key = _norm_key(col)
            for opt in options:
                if _norm_key(opt) in key:
                    return col
        return None

    full_col = col_match(["full name", "fullname", "faculty full name", "faculty name", "name"])
    short_col = col_match(["short", "code", "mentor", "initial", "3 letter", "3-letter", "faculty 3 letter"])
    dept_col = col_match(["department", "dept", "year"])
    phone_col = col_match(["phone", "mobile", "contact", "contact no", "contact number"])
    email_col = col_match(["email", "mail", "official mail", "lj official mail", "lj official mail id"])
    doj_col = col_match(["joining", "doj", "date of joining", "doj in lj"])
    type_col = col_match(["type", "designation", "role", "faculty type"])
    status_col = col_match(["status", "working", "active"])
    if not email_col:
        email_col = col_match(["mailid", "officialmailid"])
    if not doj_col:
        doj_col = col_match(["dojinlj"])
    if not type_col:
        type_col = col_match(["type"])
    if not status_col:
        status_col = col_match(["status"])

    missing_cols = []
    if not full_col:
        missing_cols.append("Full Name")
    if not short_col:
        missing_cols.append("Short Name")
    if not phone_col:
        missing_cols.append("Phone")
    if missing_cols:
        try:
            file.seek(0)
            raw = pd.read_excel(file, header=None)
            header_row = None
            best_score = 0
            for idx in range(min(10, len(raw))):
                row_vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist()]
                score = 0
                for val in row_vals:
                    if "full name" in val or "faculty full name" in val:
                        score += 2
                    if "3 letter" in val or "initial" in val or "short" in val:
                        score += 2
                    if "contact" in val or "phone" in val or "mobile" in val:
                        score += 1
                if score > best_score:
                    best_score = score
                    header_row = idx
            if header_row is not None and best_score > 0:
                file.seek(0)
                df = pd.read_excel(file, header=header_row)
                df.columns = [str(c).strip() for c in df.columns]
                full_col = col_match(["full name", "fullname", "faculty full name", "faculty name", "name"])
                short_col = col_match(["short", "code", "mentor", "initial", "3 letter", "3-letter", "faculty 3 letter"])
                dept_col = col_match(["department", "dept", "year"])
                phone_col = col_match(["phone", "mobile", "contact", "contact no", "contact number"])
                email_col = col_match(["email", "mail", "official mail", "lj official mail", "lj official mail id"])
                doj_col = col_match(["joining", "doj", "date of joining", "doj in lj"])
                type_col = col_match(["type", "designation", "role", "faculty type"])
                status_col = col_match(["status", "working", "active"])
                if not email_col:
                    email_col = col_match(["mailid", "officialmailid"])
                if not doj_col:
                    doj_col = col_match(["dojinlj"])
                if not type_col:
                    type_col = col_match(["type"])
                if not status_col:
                    status_col = col_match(["status"])
        except Exception:
            pass
        missing_cols = []
        if not full_col:
            missing_cols.append("Full Name")
        if not short_col:
            missing_cols.append("Short Name")
        if not phone_col:
            missing_cols.append("Phone")
        if missing_cols:
            raise ValueError("Missing required columns: " + ", ".join(missing_cols))

    debug_info = {
        "columns": [str(c) for c in df.columns],
        "mapped": {},
    }

    def _blank_if_placeholder(val):
        text = str(val or "").strip()
        if text in {"-", "--", "na", "n/a", "nan"}:
            return ""
        return text

    for idx, row in df.iterrows():
        full_name = safe_text(_blank_if_placeholder(row.get(full_col)), 100)
        short_name = safe_text(_blank_if_placeholder(row.get(short_col)), 50).upper()
        department = safe_text(_blank_if_placeholder(row.get(dept_col)), 30).upper() or "PENDING"
        phone = format_phone(clean_number(row.get(phone_col)))[:20]
        email = safe_text(_blank_if_placeholder(row.get(email_col)), 120)
        doj = _parse_date(_blank_if_placeholder(row.get(doj_col)))
        raw_type = _normalize_faculty_type(_blank_if_placeholder(row.get(type_col)))
        if not raw_type and short_name and len(short_name) <= 2:
            raw_type = "Peon"
        f_type = raw_type or "Faculty"
        status = _normalize_status(_blank_if_placeholder(row.get(status_col))) or "Working"

        mentor, created = Mentor.objects.get_or_create(name=short_name)
        if created:
            if not (full_name and short_name and phone):
                skipped += 1
                skipped_rows.append(
                    {
                        "row": idx + 2,
                        "name": full_name or short_name,
                        "reason": "Missing required: full name, short name, or phone",
                    }
                )
                mentor.delete()
                continue
            added += 1
        else:
            updated += 1

        resolved_full = mentor.full_name
        if full_name:
            if not mentor.full_name:
                resolved_full = full_name
            elif _names_equivalent(mentor.full_name, full_name):
                resolved_full = full_name if len(full_name) >= len(mentor.full_name) else mentor.full_name

        updates = {
            "full_name": resolved_full or mentor.full_name,
            "department": department or mentor.department,
            "phone": phone or mentor.phone,
            "email": email or mentor.email,
            "date_of_joining": doj or mentor.date_of_joining,
            "faculty_type": f_type or mentor.faculty_type,
            "status": status or mentor.status,
        }
        for key, value in updates.items():
            setattr(mentor, key, value)
        mentor.save()

        modules = _modules_for_department(department)
        if modules:
            MentorModuleAccess.objects.filter(mentor=mentor, module__in=modules).delete()
            MentorModuleAccess.objects.bulk_create(
                [MentorModuleAccess(mentor=mentor, module=m) for m in modules],
                ignore_conflicts=True,
            )

    debug_info["mapped"] = {
        "full_name": str(full_col),
        "short_name": str(short_col),
        "department": str(dept_col),
        "phone": str(phone_col),
        "email": str(email_col),
        "doj": str(doj_col),
        "type": str(type_col),
        "status": str(status_col),
    }
    return added, updated, skipped, skipped_rows, debug_info


# ---------------- NORMALIZE TEXT ----------------
def normalize(text):
    return str(text).lower().replace("\n", " ").strip()


def _compact_upper(text):
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


def _mentor_identity_queryset():
    return Mentor.objects.all()


def _mentor_by_compact_identity(raw_value):
    compact_raw = _compact_upper(raw_value)
    if not compact_raw:
        return None
    for mentor in _mentor_identity_queryset():
        if _compact_upper(mentor.name) == compact_raw or _compact_upper(mentor.full_name) == compact_raw:
            return mentor
    return None


def _mentor_by_subsequence_identity(raw_value, require_students=False):
    compact_raw = _compact_upper(raw_value)
    if not compact_raw or len(compact_raw) > 5:
        return None
    candidates = []
    for mentor in _mentor_identity_queryset():
        student_count = Student.objects.filter(mentor=mentor).count()
        if require_students and student_count == 0:
            continue
        name_compact = _compact_upper(mentor.name)
        full_compact = _compact_upper(mentor.full_name)
        if _is_subsequence(compact_raw, name_compact) or _is_subsequence(compact_raw, full_compact):
            candidates.append((student_count, mentor))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1].name))
    return candidates[0][1]


def resolve_mentor_reference(short_name="", full_name="", fallback_raw="", require_students=False):
    short_name = str(short_name or "").strip()
    full_name = str(full_name or "").strip()
    fallback_raw = str(fallback_raw or "").strip()

    if short_name:
        direct = Mentor.objects.filter(name__iexact=short_name).first()
        if direct and (not require_students or Student.objects.filter(mentor=direct).exists()):
            return direct
        compact_match = _mentor_by_compact_identity(short_name)
        if compact_match and (not require_students or Student.objects.filter(mentor=compact_match).exists()):
            return compact_match
        subseq_match = _mentor_by_subsequence_identity(short_name, require_students=require_students)
        if subseq_match:
            return subseq_match

    for candidate in [full_name, fallback_raw]:
        if not candidate:
            continue
        by_full = Mentor.objects.filter(full_name__iexact=candidate).first()
        if by_full and (not require_students or Student.objects.filter(mentor=by_full).exists()):
            return by_full
        by_name = Mentor.objects.filter(name__iexact=candidate).first()
        if by_name and (not require_students or Student.objects.filter(mentor=by_name).exists()):
            return by_name
        compact_match = _mentor_by_compact_identity(candidate)
        if compact_match and (not require_students or Student.objects.filter(mentor=compact_match).exists()):
            return compact_match

    return None


def _is_subsequence(small, big):
    it = iter(big)
    return all(ch in it for ch in small)


def resolve_mentor_identity(username):
    """
    Resolve mentor login using either short name or full name.
    Returns canonical Mentor object or None.
    """
    raw = str(username or "").strip()
    if not raw:
        return None

    resolved = resolve_mentor_reference(fallback_raw=raw, require_students=True)
    if resolved:
        return resolved
    direct = Mentor.objects.filter(name__iexact=raw).first()
    if direct:
        return direct
    return Mentor.objects.filter(full_name__iexact=raw).first()


# ---------------- DETECT HEADER ----------------
def detect_header_row(df):
    """Find row containing enrolment + mentor keywords"""

    for i in range(len(df)):
        row_text = " ".join([normalize(x) for x in df.iloc[i].values])

        if ("enrol" in row_text or "enrollment" in row_text) and ("mentor" in row_text):
            return i

    return 0


# ---------------- FIND COLUMN ----------------
def find_col(columns, keywords):

    for col in columns:
        col_norm = normalize(col)

        for key in keywords:
            if key in col_norm:
                return col

    return None


# ---------------- IMPORT STUDENTS ----------------
def import_students_from_excel(file, module):

    # read raw first
    raw = pd.read_excel(file, header=None)

    # detect header row dynamically
    header_row = detect_header_row(raw)

    # reload with header
    df = pd.read_excel(file, header=header_row)

    # normalize headers
    df.columns = [normalize(c) for c in df.columns]

    # detect columns
    enrollment_col = find_col(df.columns, ['enrol'])
    name_col = find_col(df.columns, ['name of student', 'student name', 'the name must be'])
    roll_col = find_col(df.columns, ['roll'])
    mentor_short_col = find_col(df.columns, ['short name of mentor', 'mentor short'])
    mentor_full_col = find_col(df.columns, ['name of mentor'])
    mentor_fallback_col = find_col(df.columns, ['mentor'])
    student_col = (
        find_col(df.columns, ['student no'])
        or find_col(df.columns, ['student mobile'])
        or find_col(df.columns, ['student mobile no', 'student mobile number', 'student mobileno'])
        or find_col(df.columns, ['student contact', 'student phone', 'student phone no'])
    )
    father_col = find_col(df.columns, ['parent no', 'father'])
    mother_col = find_col(df.columns, ['mother'])
    batch_col = find_col(df.columns, ['branch', 'batch'])
    division_col = (
        find_col(df.columns, ['sem ii div', 'sem 2 div', 'semester ii div', 'semester 2 div'])
        or find_col(df.columns, ['division', 'div'])
    )

    added = 0
    updated = 0
    skipped = 0

    skipped_rows = []

    for idx, row in df.iterrows():

        try:
            enrollment = clean_number(row.get(enrollment_col))
            if not enrollment:
                skipped_rows.append({
                    "row": int(idx) + 2,
                    "roll": clean_number(row.get(roll_col)),
                    "name": safe_text(row.get(name_col), 100),
                    "enrollment": "",
                    "reason": "Missing enrollment",
                })
                skipped += 1
                continue

            # model-safe values
            name = safe_text(row.get(name_col), 100)
            roll = safe_int(row.get(roll_col))
            mentor_short = safe_text(row.get(mentor_short_col), 50).upper()
            mentor_full = safe_text(row.get(mentor_full_col), 100)
            mentor_raw = safe_text(row.get(mentor_fallback_col), 100)

            # Canonical mentor code:
            # - 3 letters => short code
            # - full name => resolve via known full_name mapping, else keep as-is
            mentor_obj = resolve_mentor_reference(
                short_name=mentor_short or mentor_raw,
                full_name=mentor_full,
                fallback_raw=mentor_raw,
                require_students=False,
            )
            if mentor_obj:
                mentor_name = (mentor_obj.name or mentor_short or mentor_raw or "UNKNOWN")[:50]
            elif mentor_short:
                mentor_name = mentor_short[:50]
            elif mentor_raw and len(mentor_raw.replace(" ", "")) <= 3:
                mentor_name = mentor_raw.upper()[:50]
            else:
                full_candidate = mentor_full or mentor_raw
                mentor_name = (full_candidate or "UNKNOWN")[:50]

            student_mobile = format_phone(clean_number(row.get(student_col)))[:15]
            father = format_phone(clean_number(row.get(father_col)))[:15]
            mother = format_phone(clean_number(row.get(mother_col)))[:15]
            batch = safe_text(row.get(batch_col), 20)
            division = safe_text(row.get(division_col), 20)

            mentor, _ = Mentor.objects.get_or_create(name=mentor_name)
            if mentor_full and mentor.full_name != mentor_full:
                mentor.full_name = mentor_full
                mentor.save(update_fields=["full_name"])

            # If both full and short are available, merge old full-name mentor bucket into short-name mentor.
            if mentor_short and mentor_full:
                full_mentor_obj = Mentor.objects.filter(name__iexact=mentor_full).exclude(id=mentor.id).first()
                if full_mentor_obj:
                    Student.objects.filter(mentor=full_mentor_obj).update(mentor=mentor)
                    if not Student.objects.filter(mentor=full_mentor_obj).exists():
                        full_mentor_obj.delete()

            _, created = Student.objects.update_or_create(
                module=module,
                enrollment=enrollment[:20],
                defaults={
                    'name': name,
                    'roll_no': roll,
                    'mentor': mentor,
                    'student_mobile': student_mobile,
                    'father_mobile': father,
                    'mother_mobile': mother,
                    'batch': batch,
                    'division': division,
                }
            )

            if created:
                added += 1
            else:
                updated += 1
        except Exception as e:
            # Skip bad rows instead of failing whole upload
            skipped_rows.append({
                "row": int(idx) + 2,
                "roll": clean_number(row.get(roll_col)),
                "name": safe_text(row.get(name_col), 100),
                "enrollment": clean_number(row.get(enrollment_col)),
                "reason": str(e)[:180],
            })
            skipped += 1

    return added, updated, skipped, skipped_rows
