import re
from datetime import date, timedelta

import pandas as pd


DAY_MAP = {
    "MON": 0,
    "MONDAY": 0,
    "TUE": 1,
    "TUESDAY": 1,
    "WED": 2,
    "WEDNESDAY": 2,
    "THU": 3,
    "THUR": 3,
    "THURS": 3,
    "THURSDAY": 3,
    "FRI": 4,
    "FRIDAY": 4,
    "SAT": 5,
    "SATURDAY": 5,
    "SUN": 6,
    "SUNDAY": 6,
}


def _clean_text(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return text.replace("\n", " ").strip()


def _normalize_day(value):
    raw = _clean_text(value).upper()
    raw = raw.replace(".", "").replace(",", "").strip()
    return DAY_MAP.get(raw)


def _parse_time_piece(piece):
    piece = piece.strip().lower()
    match = re.search(r"(\d{1,2})[:.](\d{2})\s*(am|pm)?", piece)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3)
    if meridiem:
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
    return f"{hour:02d}:{minute:02d}"


def normalize_time_slot(value):
    raw = _clean_text(value)
    if not raw:
        return ""
    parts = re.split(r"\s*(?:to|-)\s*", raw, flags=re.IGNORECASE)
    if len(parts) >= 2:
        start = _parse_time_piece(parts[0]) or parts[0].strip()
        end = _parse_time_piece(parts[1]) or parts[1].strip()
        return f"{start}-{end}"
    return raw.replace(" ", "")


def _find_header_row(raw_df):
    for i in range(len(raw_df)):
        row = " ".join(_clean_text(x).lower() for x in raw_df.iloc[i].values)
        if "day" in row and "lecture" in row and "time" in row:
            return i
    return None


def _build_division_map(row):
    current = None
    mapping = {}
    for idx, cell in enumerate(row):
        val = _clean_text(cell)
        if val and "division" not in val.lower():
            current = val
        mapping[idx] = current
    return mapping


def parse_timetable_excel(file):
    xls = pd.ExcelFile(file)
    for sheet in xls.sheet_names:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        header_row = _find_header_row(raw)
        if header_row is None or header_row < 1:
            continue

        division_row = raw.iloc[header_row - 1].tolist()
        division_map = _build_division_map(division_row)
        header = raw.iloc[header_row].tolist()

        subject_cols = [i for i, h in enumerate(header) if _clean_text(h).lower() == "subject"]
        if not subject_cols:
            continue

        rows = raw.iloc[header_row + 1 :].copy()
        day_val = None
        entries = []
        for _, row in rows.iterrows():
            day_cell = row.iloc[0]
            day_code = _normalize_day(day_cell)
            if day_code is not None:
                day_val = day_code

            lecture_raw = _clean_text(row.iloc[1])
            if not lecture_raw:
                continue
            if "break" in lecture_raw.lower():
                continue
            try:
                lecture_no = int(float(lecture_raw))
            except Exception:
                continue

            time_slot = normalize_time_slot(row.iloc[2])
            if day_val is None:
                continue

            for col in subject_cols:
                division = division_map.get(col)
                if not division:
                    continue
                subject = _clean_text(row.iloc[col])
                if not subject or subject == "0":
                    continue
                faculty = _clean_text(row.iloc[col + 1]) if col + 1 < len(row) else ""
                room = _clean_text(row.iloc[col + 2]) if col + 2 < len(row) else ""
                entries.append(
                    {
                        "day_of_week": day_val,
                        "lecture_no": lecture_no,
                        "time_slot": time_slot,
                        "batch": division.strip(),
                        "subject": subject.strip(),
                        "faculty": faculty.strip(),
                        "room": room.strip(),
                    }
                )

        if entries:
            return entries, sheet

    raise ValueError("Could not detect a timetable sheet with Day/Lecture/Time headers.")


def phase_range(calendar, phase):
    if not calendar:
        return None, None
    phase = (phase or "").upper()
    if phase == "T1":
        return calendar.t1_start, calendar.t1_end
    if phase == "T2":
        return calendar.t2_start, calendar.t2_end
    if phase == "T3":
        return calendar.t3_start, calendar.t3_end
    if phase == "T4":
        return calendar.t4_start, calendar.t4_end
    return None, None


def phase_for_date(calendar, target_date):
    for phase in ["T1", "T2", "T3", "T4"]:
        start, end = phase_range(calendar, phase)
        if start and end and start <= target_date <= end:
            return phase
    return None


def week_for_date(calendar, target_date):
    phase = phase_for_date(calendar, target_date)
    if not phase:
        return None, None
    start, _ = phase_range(calendar, phase)
    if not start:
        return phase, None
    delta = (target_date - start).days
    week_no = (delta // 7) + 1
    return phase, week_no


def end_date_for_week(calendar, phase, week_no):
    start, end = phase_range(calendar, phase)
    if not start:
        return None
    if week_no is None:
        return end
    return start + timedelta(days=(week_no * 7) - 1)

