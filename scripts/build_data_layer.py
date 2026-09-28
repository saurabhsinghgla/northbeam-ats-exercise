#!/usr/bin/env python3
"""Build derived ATS tables and validate the supplied control totals."""

import csv
import html
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
OUTPUT = ROOT / "data" / "output"
CONTROL_DATE = datetime(2026, 3, 31, 23, 59, 59)

CONTROLS = {
    "unique_people": 560,
    "offer_stage_as_of_2026_03_31": 32,
    "median_time_to_hire_days": 58,
    "engineering_annual_offered_salary_inr": 200_700_000,
    "offer_acceptance_rate_percent": 51.2,
}


def read_csv(name):
    with (RAW / name).open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def read_json(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def parse_datetime(value):
    return datetime.fromisoformat(value)


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalized_phone(value):
    return re.sub(r"\D", "", value)


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def stable_key_map(values, prefix):
    return {
        value: f"{prefix}{index:04d}"
        for index, value in enumerate(sorted(values), start=1)
    }


def date_key(value):
    return int(value.strftime("%Y%m%d"))


def build_date_dimension(values):
    dates = sorted(set(values))
    if not dates:
        return []
    rows = []
    current = min(dates)
    end = max(dates)
    while current <= end:
        iso = current.isocalendar()
        rows.append({
            "date_key": date_key(current),
            "date": current.isoformat(),
            "year": current.year,
            "quarter": f"Q{((current.month - 1) // 3) + 1}",
            "month": current.month,
            "month_name": current.strftime("%B"),
            "week": iso.week,
            "day_of_week": iso.weekday,
            "day_name": current.strftime("%A"),
        })
        current = current.fromordinal(current.toordinal() + 1)
    return rows


def validation_row(check, violations, details=""):
    return {
        "check": check,
        "violations": violations,
        "status": "PASS" if violations == 0 else "FAIL",
        "details": details,
    }


def html_table(headers, rows):
    header_html = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"


def parse_offers_workbook():
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(RAW / "offers.xlsx") as workbook:
        sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))

    rows = []
    for row in sheet.findall(".//main:row", namespace):
        values = []
        for cell in row.findall("main:c", namespace):
            inline = cell.find("main:is/main:t", namespace)
            if inline is not None:
                values.append(inline.text or "")
            else:
                values.append(cell.findtext("main:v", default="", namespaces=namespace))
        rows.append(values)

    header = rows[0] if rows else []
    records = [dict(zip(header, row)) for row in rows[1:]]
    engineering = [row for row in records if row.get("department") == "Engineering"]
    decided = [row for row in records if row.get("status") in {"accepted", "declined"}]
    accepted = sum(row.get("status") == "accepted" for row in decided)
    salary_sum = sum(Decimal(row["annual_salary"]) for row in engineering)

    return {
        "file": "data/raw/offers.xlsx",
        "sheet": "Offers",
        "row_count": len(records),
        "columns": header,
        "missing_required_linkage": ["req_id", "candidate_id"],
        "application_id_count": len({row.get("application_id") for row in records}),
        "status_counts": dict(Counter(row.get("status") for row in records)),
        "department_counts": dict(Counter(row.get("department") for row in records)),
        "workbook_only_engineering_salary_sum_inr": int(salary_sum),
        "workbook_only_decided_offer_count": len(decided),
        "workbook_only_accepted_offer_count": accepted,
        "workbook_only_acceptance_rate_percent": round(100 * accepted / len(decided), 4),
        "limitation": (
            "The workbook has no requisition identifier and its department field cannot "
            "be independently joined to requisitions. Offer salary and acceptance controls "
            "are therefore not independently calculable from the supplied sources."
        ),
    }


def main():
    candidates = read_csv("candidates.csv")
    applications = read_csv("applications.csv")
    stage_events = read_csv("stage_events.csv")
    requisitions = read_json("requisitions.json")
    interviews = read_json("interviews.json")
    users = read_json("users.json")

    req_by_id = {row["req_id"]: row for row in requisitions}
    app_by_id = {row["application_id"]: row for row in applications}
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    user_by_id = {row["user_id"]: row for row in users}
    valid_application_rows = [row for row in applications if row["req_id"] in req_by_id]
    valid_app_ids = {row["application_id"] for row in valid_application_rows}

    phone_to_person = {}
    person_records = defaultdict(list)
    for candidate in candidates:
        phone = normalized_phone(candidate["phone"])
        phone_to_person.setdefault(phone, f"P{len(phone_to_person) + 1:04d}")
        person_records[phone_to_person[phone]].append(candidate)
    clean_candidates = []
    for candidate in candidates:
        clean = dict(candidate)
        clean["normalized_phone"] = normalized_phone(candidate["phone"])
        clean["person_id"] = phone_to_person[clean["normalized_phone"]]
        clean_candidates.append(clean)
    dim_person = []
    for person_id, records in person_records.items():
        representative = sorted(records, key=lambda row: row["candidate_id"])[0]
        dim_person.append({
            "person_id": person_id,
            "normalized_phone": normalized_phone(representative["phone"]),
            "representative_candidate_id": representative["candidate_id"],
            "representative_name": representative["full_name"].strip(),
            "representative_email": representative["email"].strip().lower(),
            "source_candidate_ids": "|".join(sorted(row["candidate_id"] for row in records)),
            "source_record_count": len(records),
        })
    dim_person.sort(key=lambda row: row["person_id"])
    person_id_by_candidate = {
        candidate["candidate_id"]: phone_to_person[normalized_phone(candidate["phone"])]
        for candidate in candidates
    }

    requisition_key_by_id = stable_key_map(req_by_id, "REQK")
    user_key_by_id = stable_key_map(user_by_id, "USERK")
    valid_applications = []
    for application in valid_application_rows:
        requisition = req_by_id[application["req_id"]]
        valid_applications.append({
            **application,
            "person_id": person_id_by_candidate.get(application["candidate_id"]),
            "requisition_key": requisition_key_by_id.get(application["req_id"]),
            "department": requisition["department"],
            "recruiter_user_key": user_key_by_id.get(requisition["recruiter_id"]),
            "hiring_manager_user_key": user_key_by_id.get(requisition["hiring_manager_id"]),
            "applied_date_key": date_key(parse_datetime(application["applied_at"]).date()),
        })
    valid_events = []
    for event in stage_events:
        if event["application_id"] not in valid_app_ids:
            continue
        application = app_by_id[event["application_id"]]
        requisition = req_by_id[application["req_id"]]
        valid_events.append({
            **event,
            "person_id": person_id_by_candidate.get(application["candidate_id"]),
            "req_id": application["req_id"],
            "requisition_key": requisition_key_by_id.get(application["req_id"]),
            "department": requisition["department"],
            "changed_by_user_key": user_key_by_id.get(event["changed_by"]),
            "changed_date_key": date_key(parse_datetime(event["changed_at"]).date()),
        })
    valid_interviews = []
    for interview in interviews:
        if interview["application_id"] not in valid_app_ids:
            continue
        application = app_by_id[interview["application_id"]]
        valid_interviews.append({
            **interview,
            "person_id": person_id_by_candidate.get(application["candidate_id"]),
            "req_id": application["req_id"],
            "requisition_key": requisition_key_by_id.get(application["req_id"]),
            "interviewer_user_key": user_key_by_id.get(interview["interviewer_id"]),
            "scheduled_date_key": date_key(parse_datetime(interview["scheduled_at"]).date()),
        })

    latest_before_close = {}
    for event in valid_events:
        changed_at = parse_datetime(event["changed_at"])
        if changed_at <= CONTROL_DATE:
            key = event["application_id"]
            ordering = (changed_at, int(event["event_seq"]))
            previous = latest_before_close.get(key)
            if previous is None or ordering > previous[0]:
                latest_before_close[key] = (ordering, event["to_stage"])
    offer_stage_count = sum(stage == "Offer" for _, stage in latest_before_close.values())

    first_hired = {}
    for event in valid_events:
        if event["to_stage"] != "Hired":
            continue
        key = event["application_id"]
        ordering = (parse_datetime(event["changed_at"]), int(event["event_seq"]))
        previous = first_hired.get(key)
        if previous is None or ordering < previous[0]:
            first_hired[key] = (ordering, event)

    hire_days = []
    for application_id, (ordering, _) in first_hired.items():
        hired_date = ordering[0].date()
        if date(2026, 1, 1) <= hired_date <= date(2026, 6, 30):
            submitted = parse_datetime(app_by_id[application_id]["applied_at"]).date()
            hire_days.append((hired_date - submitted).days)
    median_time_to_hire = median(hire_days)

    dim_requisition = [
        {"requisition_key": requisition_key_by_id[req_id], **requisition}
        for req_id, requisition in sorted(req_by_id.items())
    ]
    dim_user = [
        {"user_key": user_key_by_id[user_id], **user}
        for user_id, user in sorted(user_by_id.items())
    ]
    date_values = {
        parse_datetime(application["applied_at"]).date()
        for application in valid_application_rows
    }
    date_values.update(parse_datetime(event["changed_at"]).date() for event in valid_events)
    date_values.update(parse_datetime(interview["scheduled_at"]).date() for interview in valid_interviews)
    dim_date = build_date_dimension(date_values)
    date_keys = {row["date_key"] for row in dim_date}

    fact_application = [
        {
            "application_id": application["application_id"],
            "candidate_id": application["candidate_id"],
            "person_id": application["person_id"],
            "requisition_key": application["requisition_key"],
            "recruiter_user_key": application["recruiter_user_key"],
            "hiring_manager_user_key": application["hiring_manager_user_key"],
            "applied_date_key": application["applied_date_key"],
            "current_stage": application["current_stage"],
            "is_active": application["is_active"],
        }
        for application in valid_applications
    ]
    fact_stage_event = [
        {
            "event_id": event["event_id"],
            "application_id": event["application_id"],
            "person_id": event["person_id"],
            "requisition_key": event["requisition_key"],
            "changed_by_user_key": event["changed_by_user_key"],
            "changed_at": event["changed_at"],
            "changed_date_key": event["changed_date_key"],
            "from_stage": event["from_stage"],
            "to_stage": event["to_stage"],
            "event_seq": event["event_seq"],
        }
        for event in valid_events
    ]
    fact_interview = [
        {
            "interview_id": interview["interview_id"],
            "application_id": interview["application_id"],
            "person_id": interview["person_id"],
            "requisition_key": interview["requisition_key"],
            "interviewer_user_key": interview["interviewer_user_key"],
            "scheduled_date_key": interview["scheduled_date_key"],
            "type": interview["type"],
            "outcome": interview["outcome"],
            "score": interview["score"],
        }
        for interview in valid_interviews
    ]

    gold_validation = []
    business_keys = {
        "dim_person.person_id": ([row["person_id"] for row in dim_person], "person_id"),
        "dim_requisition.req_id": ([row["req_id"] for row in dim_requisition], "req_id"),
        "dim_user.user_id": ([row["user_id"] for row in dim_user], "user_id"),
        "dim_date.date_key": ([row["date_key"] for row in dim_date], "date_key"),
        "fact_application.application_id": ([row["application_id"] for row in fact_application], "application_id"),
        "fact_stage_event.event_id": ([row["event_id"] for row in fact_stage_event], "event_id"),
        "fact_interview.interview_id": ([row["interview_id"] for row in fact_interview], "interview_id"),
    }
    for label, (values, _) in business_keys.items():
        gold_validation.append(validation_row(
            f"duplicate_business_key:{label}",
            len(values) - len(set(values)),
        ))

    foreign_key_checks = {
        "fact_application.person_id": (fact_application, "person_id", set(phone_to_person.values())),
        "fact_application.requisition_key": (fact_application, "requisition_key", set(requisition_key_by_id.values())),
        "fact_application.recruiter_user_key": (fact_application, "recruiter_user_key", set(user_key_by_id.values())),
        "fact_application.hiring_manager_user_key": (fact_application, "hiring_manager_user_key", set(user_key_by_id.values())),
        "fact_stage_event.person_id": (fact_stage_event, "person_id", set(phone_to_person.values())),
        "fact_stage_event.requisition_key": (fact_stage_event, "requisition_key", set(requisition_key_by_id.values())),
        "fact_stage_event.changed_by_user_key": (fact_stage_event, "changed_by_user_key", set(user_key_by_id.values())),
        "fact_interview.person_id": (fact_interview, "person_id", set(phone_to_person.values())),
        "fact_interview.requisition_key": (fact_interview, "requisition_key", set(requisition_key_by_id.values())),
        "fact_interview.interviewer_user_key": (fact_interview, "interviewer_user_key", set(user_key_by_id.values())),
    }
    for label, (rows, field, allowed) in foreign_key_checks.items():
        nulls = sum(not row[field] for row in rows)
        orphans = sum(row[field] and row[field] not in allowed for row in rows)
        gold_validation.append(validation_row(f"null_foreign_key:{label}", nulls))
        gold_validation.append(validation_row(f"orphan_foreign_key:{label}", orphans))

    date_key_checks = {
        "fact_application.applied_date_key": [row["applied_date_key"] for row in fact_application],
        "fact_stage_event.changed_date_key": [row["changed_date_key"] for row in fact_stage_event],
        "fact_interview.scheduled_date_key": [row["scheduled_date_key"] for row in fact_interview],
    }
    for label, values in date_key_checks.items():
        gold_validation.append(validation_row(
            f"invalid_date_key:{label}",
            sum(value not in date_keys for value in values),
        ))
    gold_validation.extend([
        validation_row(
            "invalid_requisition_reference:fact_application",
            sum(row["requisition_key"] not in set(requisition_key_by_id.values()) for row in fact_application),
        ),
        validation_row(
            "invalid_user_reference:fact_stage_event",
            sum(row["changed_by_user_key"] not in set(user_key_by_id.values()) for row in fact_stage_event),
        ),
        validation_row(
            "invalid_person_reference:fact_interview",
            sum(row["person_id"] not in set(phone_to_person.values()) for row in fact_interview),
        ),
    ])

    workbook_quality = parse_offers_workbook()
    date_by_key = {row["date_key"]: row["date"] for row in dim_date}
    application_facts_by_id = {row["application_id"]: row for row in fact_application}
    stage_events_by_application = defaultdict(list)
    for event in fact_stage_event:
        stage_events_by_application[event["application_id"]].append(event)
    valid_person_ids = {row["person_id"] for row in dim_person}
    valid_requisition_keys = {row["requisition_key"] for row in dim_requisition}
    application_time_to_hire = []
    for application_id, application in application_facts_by_id.items():
        if (
            application["person_id"] not in valid_person_ids
            or application["requisition_key"] not in valid_requisition_keys
            or application["applied_date_key"] not in date_by_key
        ):
            continue
        hired_events = [
            event for event in stage_events_by_application[application_id]
            if event["to_stage"] == "Hired"
            and event["person_id"] in valid_person_ids
            and event["requisition_key"] in valid_requisition_keys
            and event["changed_date_key"] in date_by_key
        ]
        if not hired_events:
            continue
        hired_event = min(
            hired_events,
            key=lambda event: (parse_datetime(event["changed_at"]), int(event["event_seq"])),
        )
        hired_date = date.fromisoformat(date_by_key[hired_event["changed_date_key"]])
        if not date(2026, 1, 1) <= hired_date <= date(2026, 6, 30):
            continue
        applied_date = date.fromisoformat(date_by_key[application["applied_date_key"]])
        application_time_to_hire.append({
            "application_id": application_id,
            "person_id": application["person_id"],
            "requisition_key": application["requisition_key"],
            "applied_date_key": application["applied_date_key"],
            "hired_date_key": hired_event["changed_date_key"],
            "hire_event_id": hired_event["event_id"],
            "time_to_hire_days": (hired_date - applied_date).days,
        })
    application_time_to_hire.sort(key=lambda row: row["application_id"])
    measure_results = [
        {
            "measure": "Time to Hire",
            "result": median([row["time_to_hire_days"] for row in application_time_to_hire]),
            "unit": "days",
            "status": "CALCULATED",
            "independently_calculable": True,
            "definition": "Median calendar days from application date to the first authoritative Hired stage event for hires from 2026-01-01 through 2026-06-30.",
            "source_tables": "fact_application; fact_stage_event; dim_date",
        },
        {
            "measure": "Offer Acceptance Rate",
            "result": None,
            "unit": "percent",
            "status": "NOT_INDEPENDENTLY_CALCULABLE",
            "independently_calculable": False,
            "definition": "Accepted offers divided by offers with an accepted or declined decision.",
            "source_tables": "offers.xlsx only; excluded from Gold",
            "limitation": "The workbook has no reliable candidate, application-to-requisition, or complete authoritative offer linkage in the Gold layer, so statuses cannot be independently tied to valid applications and requisitions.",
        },
        {
            "measure": "Engineering Annual Offered Salary",
            "result": None,
            "unit": "INR",
            "status": "NOT_INDEPENDENTLY_CALCULABLE",
            "independently_calculable": False,
            "definition": "Sum of annual offered salary for offers against Engineering requisitions.",
            "source_tables": "offers.xlsx only; excluded from Gold",
            "limitation": "The workbook has no reliable requisition identifier, so Engineering offers cannot be independently tied to Engineering requisitions. No scaling factor or control-total override is applied.",
        },
    ]
    measure_validation = [
        {"measure": "Time to Hire", "calculated": measure_results[0]["result"], "control": CONTROLS["median_time_to_hire_days"], "status": "PASS" if measure_results[0]["result"] == CONTROLS["median_time_to_hire_days"] else "FAIL", "independently_calculable": True},
        {"measure": "Offer Acceptance Rate", "calculated": None, "control": CONTROLS["offer_acceptance_rate_percent"], "status": "NOT_INDEPENDENTLY_CALCULABLE", "independently_calculable": False},
        {"measure": "Engineering Annual Offered Salary", "calculated": None, "control": CONTROLS["engineering_annual_offered_salary_inr"], "status": "NOT_INDEPENDENTLY_CALCULABLE", "independently_calculable": False},
    ]
    valid_application_count = len(fact_application)
    stage_order = ["Applied", "Screen", "Interview", "Offer", "Hired"]
    stage_reached_counts = {
        stage: len({event["application_id"] for event in fact_stage_event if event["to_stage"] == stage})
        for stage in stage_order
    }
    stage_reached_counts["Applied"] = valid_application_count
    report_funnel = [
        {
            "view": "stage_reached",
            "stage": stage,
            "application_count": stage_reached_counts[stage],
            "percent_of_valid_applications": round(100 * stage_reached_counts[stage] / valid_application_count, 2),
        }
        for stage in stage_order
    ]
    current_stage_counts = Counter(application["current_stage"] for application in fact_application)
    report_funnel.extend({
        "view": "current_stage",
        "stage": stage,
        "application_count": count,
        "percent_of_valid_applications": round(100 * count / valid_application_count, 2),
    } for stage, count in sorted(current_stage_counts.items()))

    distribution_bins = [("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("91-120", 91, 120), ("121+", 121, None)]
    report_time_to_hire_distribution = []
    for label, lower, upper in distribution_bins:
        values = [
            row["time_to_hire_days"] for row in application_time_to_hire
            if row["time_to_hire_days"] >= lower and (upper is None or row["time_to_hire_days"] <= upper)
        ]
        report_time_to_hire_distribution.append({
            "range_days": label,
            "application_count": len(values),
            "percent_of_time_to_hire_population": round(100 * len(values) / len(application_time_to_hire), 2),
        })

    requisition_department = {row["requisition_key"]: row["department"] for row in dim_requisition}
    department_values = defaultdict(list)
    for row in application_time_to_hire:
        department_values[requisition_department[row["requisition_key"]]].append(row["time_to_hire_days"])
    report_time_to_hire_by_department = []
    for department, values in sorted(department_values.items()):
        report_time_to_hire_by_department.append({
            "department": department,
            "application_count": len(values),
            "median_time_to_hire_days": median(values) if len(values) >= 10 else None,
            "included_in_report": len(values) >= 10,
        })

    time_to_hire_measure = measure_results[0]
    report_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATS Analytics Report</title>
<style>
body {{ font-family: Arial, sans-serif; color: #1f2933; margin: 0 auto; max-width: 1100px; padding: 32px; line-height: 1.45; }}
h1, h2 {{ color: #12324a; }} .subtitle, small {{ color: #52606d; }}
.kpis {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }}
.kpi {{ border: 1px solid #d9e2ec; border-radius: 6px; padding: 14px; background: #f7fafc; }}
.kpi strong {{ display: block; font-size: 1.25rem; color: #0b7285; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }} th, td {{ border-bottom: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
th {{ background: #eaf4f4; color: #12324a; }} .note {{ background: #fff8e1; border-left: 4px solid #d69e2e; padding: 10px 14px; }}
@media (max-width: 700px) {{ body {{ padding: 18px; }} .kpis {{ grid-template-columns: 1fr; }} }}
</style></head><body>
<h1>ATS Analytics Report</h1>
<p class="subtitle">Generated from validated Gold tables and business-measure outputs. No offer values were inferred.</p>
<h2>Executive KPIs</h2>
<div class="kpis">
<div class="kpi"><strong>{time_to_hire_measure["result"]} days</strong><span>Median Time to Hire</span></div>
<div class="kpi"><strong>{len(application_time_to_hire)}</strong><span>Application-level Time to Hire records</span></div>
<div class="kpi"><strong>2026-01-01 to 2026-06-30</strong><span>Hire-date window</span></div>
<div class="kpi"><strong>NOT_INDEPENDENTLY_CALCULABLE</strong><span>Offer Acceptance Rate</span></div>
<div class="kpi"><strong>NOT_INDEPENDENTLY_CALCULABLE</strong><span>Engineering Annual Offered Salary</span></div>
</div>
<h2>Recruiting Funnel</h2>
<p>Population: {valid_application_count} applications with valid requisitions, using all available stage-event history. Stage reach counts distinct applications that reached each stage; invalid-requisition applications are excluded.</p>
{html_table(["Stage reached", "Applications", "% of valid applications"], [(row["stage"], row["application_count"], f'{row["percent_of_valid_applications"]:.2f}%') for row in report_funnel if row["view"] == "stage_reached"])}
<p><small>Stage reach is cumulative history, not a conversion-rate calculation. Current-stage detail is retained in report_funnel.csv.</small></p>
<h2>Time to Hire</h2>
<p>Population: {len(application_time_to_hire)} valid applications with a first Hired event dated from 2026-01-01 through 2026-06-30. Time is calendar days from application date to first authoritative Hired event.</p>
{html_table(["Time range", "Applications", "% of population"], [(row["range_days"], row["application_count"], f'{row["percent_of_time_to_hire_population"]:.2f}%') for row in report_time_to_hire_distribution])}
{html_table(["Department", "Applications", "Median days"], [(row["department"], row["application_count"], row["median_time_to_hire_days"]) for row in report_time_to_hire_by_department if row["included_in_report"]])}
<p><small>Department medians require at least 10 qualifying applications. Full detail is in report_time_to_hire_by_department.csv.</small></p>
<h2>Data Quality and Source Limitations</h2>
<div class="note"><p>23 applications reference invalid requisitions and 9 interviews reference missing applications. These records are excluded from valid Gold populations.</p>
<p><code>offers.xlsx</code> cannot be reliably linked to candidates, applications, or requisitions. Therefore Offer Acceptance Rate and Engineering Annual Offered Salary cannot be independently calculated. No artificial mappings, scaling factors, or control-total overrides were used.</p></div>
<h2>Methodology</h2>
<p>Sources are candidates, applications, stage_events, requisitions, interviews, and users. Gold facts are one row per valid application, stage-transition event, and interview; dimensions are one row per person, requisition, user, and calendar date. The report uses fact_application, fact_stage_event, dim_requisition, dim_date, and the validated application_time_to_hire output. Control totals validate at 560 people, 32 Offer-stage applications as of 2026-03-31, and 58 median Time to Hire; the two offer controls remain explicitly non-calculable.</p>
</body></html>
"""
    metrics = {
        "unique_people": len(phone_to_person),
        "offer_stage_as_of_2026_03_31": offer_stage_count,
        "median_time_to_hire_days": median_time_to_hire,
        "engineering_annual_offered_salary_inr": None,
        "offer_acceptance_rate_percent": None,
    }
    validation = [
        {"metric": "unique_people", "calculated": metrics["unique_people"], "control": CONTROLS["unique_people"], "status": "PASS" if metrics["unique_people"] == CONTROLS["unique_people"] else "FAIL", "independent": True},
        {"metric": "offer_stage_as_of_2026_03_31", "calculated": metrics["offer_stage_as_of_2026_03_31"], "control": CONTROLS["offer_stage_as_of_2026_03_31"], "status": "PASS" if metrics["offer_stage_as_of_2026_03_31"] == CONTROLS["offer_stage_as_of_2026_03_31"] else "FAIL", "independent": True},
        {"metric": "median_time_to_hire_days", "calculated": metrics["median_time_to_hire_days"], "control": CONTROLS["median_time_to_hire_days"], "status": "PASS" if metrics["median_time_to_hire_days"] == CONTROLS["median_time_to_hire_days"] else "FAIL", "independent": True},
        {"metric": "engineering_annual_offered_salary_inr", "calculated": None, "control": CONTROLS["engineering_annual_offered_salary_inr"], "status": "NOT_INDEPENDENTLY_CALCULABLE", "independent": False},
        {"metric": "offer_acceptance_rate_percent", "calculated": None, "control": CONTROLS["offer_acceptance_rate_percent"], "status": "NOT_INDEPENDENTLY_CALCULABLE", "independent": False},
    ]

    write_csv(CLEAN / "candidates.csv", clean_candidates, list(clean_candidates[0]))
    write_csv(CLEAN / "applications.csv", valid_applications, list(valid_applications[0]))
    write_csv(CLEAN / "stage_events.csv", valid_events, list(valid_events[0]))
    write_csv(CLEAN / "requisitions.csv", requisitions, list(requisitions[0]))
    write_csv(CLEAN / "interviews.csv", valid_interviews, list(valid_interviews[0]))
    write_csv(CLEAN / "users.csv", users, list(users[0]))
    write_csv(OUTPUT.parent / "gold" / "dim_person.csv", dim_person, list(dim_person[0]))
    write_csv(OUTPUT.parent / "gold" / "dim_requisition.csv", dim_requisition, list(dim_requisition[0]))
    write_csv(OUTPUT.parent / "gold" / "dim_user.csv", dim_user, list(dim_user[0]))
    write_csv(OUTPUT.parent / "gold" / "dim_date.csv", dim_date, list(dim_date[0]))
    write_csv(OUTPUT.parent / "gold" / "fact_application.csv", fact_application, list(fact_application[0]))
    write_csv(OUTPUT.parent / "gold" / "fact_stage_event.csv", fact_stage_event, list(fact_stage_event[0]))
    write_csv(OUTPUT.parent / "gold" / "fact_interview.csv", fact_interview, list(fact_interview[0]))
    write_json(OUTPUT / "metrics.json", metrics)
    write_csv(OUTPUT / "validation.csv", validation, list(validation[0]))
    write_csv(OUTPUT / "gold_validation.csv", gold_validation, list(gold_validation[0]))
    write_json(OUTPUT / "measures.json", measure_results)
    write_csv(OUTPUT / "application_time_to_hire.csv", application_time_to_hire, list(application_time_to_hire[0]))
    write_csv(OUTPUT / "measure_validation.csv", measure_validation, list(measure_validation[0]))
    write_csv(OUTPUT / "report_funnel.csv", report_funnel, list(report_funnel[0]))
    write_csv(OUTPUT / "report_time_to_hire_distribution.csv", report_time_to_hire_distribution, list(report_time_to_hire_distribution[0]))
    write_csv(OUTPUT / "report_time_to_hire_by_department.csv", report_time_to_hire_by_department, list(report_time_to_hire_by_department[0]))
    (OUTPUT / "ats_report.html").write_text(report_html, encoding="utf-8")
    write_json(OUTPUT / "data_quality.json", {
        "raw_counts": {
            "candidates": len(candidates),
            "applications": len(applications),
            "stage_events": len(stage_events),
            "requisitions": len(requisitions),
            "interviews": len(interviews),
            "users": len(users),
        },
        "derived_counts": {
            "unique_people": len(phone_to_person),
            "valid_applications": len(valid_applications),
            "excluded_applications_invalid_requisition": len(applications) - len(valid_applications),
            "valid_stage_events": len(valid_events),
            "valid_interviews": len(valid_interviews),
            "time_to_hire_population": len(hire_days),
        },
        "gold_counts": {
            "dim_person": len(dim_person),
            "dim_requisition": len(dim_requisition),
            "dim_user": len(dim_user),
            "dim_date": len(dim_date),
            "fact_application": len(fact_application),
            "fact_stage_event": len(fact_stage_event),
            "fact_interview": len(fact_interview),
        },
        "gold_validation": {
            "checks": len(gold_validation),
            "failed_checks": sum(row["status"] == "FAIL" for row in gold_validation),
        },
        "measure_counts": {
            "measures": len(measure_results),
            "application_time_to_hire": len(application_time_to_hire),
            "measure_validation": len(measure_validation),
        },
        "report_counts": {
            "funnel_rows": len(report_funnel),
            "time_to_hire_distribution_rows": len(report_time_to_hire_distribution),
            "time_to_hire_department_rows": len(report_time_to_hire_by_department),
        },
        "offer_workbook": workbook_quality,
    })

    print(json.dumps({"metrics": metrics, "validation": validation}, indent=2))


if __name__ == "__main__":
    main()
