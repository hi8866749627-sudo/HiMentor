import pandas as pd
from .models import Mentor, Student


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

    # add country code
    if len(num) == 10:
        num = "91" + num

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


# ---------------- NORMALIZE TEXT ----------------
def normalize(text):
    return str(text).lower().replace("\n", " ").strip()


def _compact_upper(text):
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


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

    # 1) Exact name match (short/full stored in Mentor.name)
    direct = Mentor.objects.filter(name__iexact=raw).first()
    if direct and Student.objects.filter(mentor=direct).exists():
        return direct

    # 2) Exact full_name match
    by_full = Mentor.objects.filter(full_name__iexact=raw).first()
    if by_full and Student.objects.filter(mentor=by_full).exists():
        return by_full

    # 3) Compact exact comparison (ignores spaces/symbols)
    compact_raw = _compact_upper(raw)
    for m in Mentor.objects.all():
        if _compact_upper(m.name) == compact_raw or _compact_upper(m.full_name) == compact_raw:
            if Student.objects.filter(mentor=m).exists():
                return m

    # 4) If entered value is short code and direct match has no students,
    #    map code to a full-name mentor using subsequence match (HDS -> HARDIK SHAH).
    if len(compact_raw) <= 5:
        candidates = []
        for m in Mentor.objects.all():
            student_count = Student.objects.filter(mentor=m).count()
            if student_count == 0:
                continue
            name_compact = _compact_upper(m.name)
            full_compact = _compact_upper(m.full_name)
            if _is_subsequence(compact_raw, name_compact) or _is_subsequence(compact_raw, full_compact):
                candidates.append((student_count, m))
        if candidates:
            candidates.sort(key=lambda x: (-x[0], x[1].name))
            return candidates[0][1]

    # 5) Fall back to direct mentor row even if no students (keeps current behavior for unknown mappings)
    if direct:
        return direct
    return by_full


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
            mentor_name = ""
            if mentor_short:
                mentor_name = mentor_short[:50]
            elif mentor_raw and len(mentor_raw.replace(" ", "")) <= 3:
                mentor_name = mentor_raw.upper()[:50]
            else:
                full_candidate = mentor_full or mentor_raw
                if full_candidate:
                    matched = Mentor.objects.filter(full_name__iexact=full_candidate).first()
                    mentor_name = (matched.name if matched else full_candidate)[:50]
                else:
                    mentor_name = "UNKNOWN"

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
