# ATS Data Layer

## Run

From the repository root:

```bash
python scripts/build_data_layer.py
```

The pipeline uses only the Python standard library. It reads files under `data/raw/` and writes derived tables and reports under `data/clean/` and `data/output/`. It never writes to `data/raw/`.

## Medallion architecture

```text
RAW -> CLEAN -> GOLD -> measures and report
```

- **RAW** (`data/raw/`) contains the authoritative, immutable ATS exports. No cleaning or business interpretation is written back to this layer.
- **CLEAN** (`data/clean/`) contains normalized source-aligned tables, valid requisition joins, propagated person IDs, and filtered records suitable for modeling.
- **GOLD** (`data/gold/`) contains the dimensional model: conformed dimensions and application, stage-event, and interview facts with deterministic warehouse keys.
- **Measures and report** (`data/output/`) contains validated measures, report-support datasets, diagnostics, validation results, and the generated HTML report.

## Source authority

- `candidates.csv`: candidate records and phone-based person identity.
- `applications.csv`: application submissions and application-to-requisition links.
- `stage_events.csv`: authoritative stage history.
- `requisitions.json`: requisition validity and department.
- `interviews.json`: interview records.
- `users.json`: ATS users.
- `offers.xlsx`: offer diagnostics only. It is treated as malformed/incomplete for offer controls.

All five controls exclude applications that cannot be joined to a requisition. The pipeline therefore keeps only applications whose `req_id` exists in `requisitions.json`, and applies that same scope to stage events and interviews.

## Transformations

- Candidates are assigned a deterministic `person_id` from normalized phone digits. This produces 560 people from 601 candidate records. Phone is used because the extract has no separate person identifier; names and emails are not assumed to be unique.
- Applications are inner-joined to requisitions and receive the requisition department.
- Stage events are filtered to valid applications and receive `req_id` and department.
- The offer-stage snapshot uses the latest event by `changed_at`, then `event_seq`, at or before `2026-03-31 23:59:59`. It does not use the denormalized `applications.current_stage` value.
- Time to hire uses the first `Hired` event for each valid application. It includes hires dated from `2026-01-01` through `2026-06-30`, inclusive, and measures calendar days from the application date to the hired date.
- Interviews are retained only when their application has a valid requisition.
- The workbook is parsed with the standard-library ZIP/XML modules for quality diagnostics. No offer salary or decision is promoted into the clean layer.

## Outputs

- `data/clean/candidates.csv`: candidate records with normalized phone and person ID.
- `data/clean/applications.csv`: valid applications enriched with department.
- `data/clean/stage_events.csv`: valid stage history enriched with requisition and department.
- `data/clean/requisitions.csv`, `interviews.csv`, `users.csv`: normalized JSON-derived tables.
- `data/output/metrics.json`: calculated metrics, with unavailable offer metrics represented as `null`.
- `data/output/validation.csv`: comparison of calculated values with control totals.
- `data/gold/dim_person.csv`: one row per deduplicated person, retaining source candidate IDs.
- `data/gold/dim_requisition.csv`: one row per requisition with a deterministic `requisition_key`.
- `data/gold/dim_user.csv`: one row per ATS user with a deterministic `user_key`.
- `data/gold/dim_date.csv`: one row per calendar date used by Gold facts with a numeric `date_key`.
- `data/gold/fact_application.csv`: one row per valid application.
- `data/gold/fact_stage_event.csv`: one row per valid stage-transition event.
- `data/gold/fact_interview.csv`: one row per valid interview.
- `data/output/data_quality.json`: source counts, exclusions, workbook diagnostics, and limitations.
- `data/output/gold_validation.csv`: duplicate-key, null-key, orphan-key, and date-key checks for Gold tables.
- `data/output/measures.json`: exactly three business-measure definitions and results.
- `data/output/application_time_to_hire.csv`: one row per qualifying application-level Time to Hire value.
- `data/output/measure_validation.csv`: measure results compared with supplied control totals.
- `data/output/ats_report.html`: concise generated ATS analytics report.
- `data/output/report_funnel.csv`: stage-reach and current-stage report inputs.
- `data/output/report_time_to_hire_distribution.csv`: binned Time to Hire report inputs.
- `data/output/report_time_to_hire_by_department.csv`: department-level Time to Hire report inputs.

## Gold schema and grains

The Gold layer retains source business keys and adds deterministic warehouse keys. Requisition keys are assigned by sorted `req_id`; user keys are assigned by sorted `user_id`. Person keys preserve the existing normalized-phone logic and are propagated through all facts.

| Gold table | Grain | Key relationships |
| --- | --- | --- |
| `dim_person` | One row per deduplicated person | `person_id` is the primary key; `source_candidate_ids` preserves contributing source records |
| `dim_requisition` | One row per requisition | `requisition_key` is the warehouse key; `req_id` is the source business key |
| `dim_user` | One row per ATS user | `user_key` is the warehouse key; `user_id` is the source business key |
| `dim_date` | One row per calendar date between the minimum and maximum Gold fact date | `date_key` is `YYYYMMDD` |
| `fact_application` | One row per valid application | References person, requisition, recruiter, hiring manager, and applied date |
| `fact_stage_event` | One row per valid stage-transition event | References person, requisition, changing user, and changed date |
| `fact_interview` | One row per valid interview | References person, requisition, interviewer, and scheduled date |

Gold validation currently executes 33 checks. It checks duplicate business keys for every dimension and fact, null and orphan foreign keys for fact references, invalid date keys, and explicit requisition, user, and person references.

## Business measures

The measure layer uses only validated Gold facts and dimensions. It does not create a report or dashboard and does not promote the malformed offer workbook into Gold.

| Measure | Grain/result | Source tables | Filters and calculation |
| --- | --- | --- | --- |
| Time to Hire | One application-level row in `application_time_to_hire.csv`; overall median in `measures.json` | `fact_application`, `fact_stage_event`, `dim_date` | Keep valid person and requisition references; choose the first `Hired` event by `changed_at`, then `event_seq`; keep hired dates from 2026-01-01 through 2026-06-30; subtract application date from hired date in calendar days |
| Offer Acceptance Rate | One overall result in `measures.json` | No valid Gold offer fact; workbook diagnostic only | Not independently calculable because the workbook cannot reliably link offer decisions to valid application and requisition records; output is `NOT_INDEPENDENTLY_CALCULABLE` |
| Engineering Annual Offered Salary | One overall result in `measures.json` | No valid Gold offer fact; workbook diagnostic only | Not independently calculable because the workbook has no reliable requisition identifier; output is `NOT_INDEPENDENTLY_CALCULABLE` and no scaling or control-total override is applied |

Time to Hire produces 97 application-level rows and an overall median of 58 days. The two offer measures retain their supplied control totals only in `measure_validation.csv`; their calculated values remain null because the available data does not support an independent result.

## Reporting layer

`data/output/ats_report.html` is generated by the pipeline from Gold tables and the validated measure outputs. It contains one executive KPI section, a recruiting funnel, a Time to Hire distribution, a supported department breakdown, source limitations, and methodology.

- Funnel scope: 1,427 valid applications with a valid requisition, all available stage-event history, no event-date filter. Stage reach is the distinct application count reaching each stage; it is not presented as a conversion rate.
- Time to Hire scope: 97 valid application-level records with a first Hired event dated from 2026-01-01 through 2026-06-30. Values are calendar days from application date to first authoritative Hired event.
- Department scope: the same 97-record Time to Hire population. Department medians are displayed only when a department has at least 10 qualifying applications; Finance has 6 and is retained in the supporting CSV but omitted from the report table.
- Offer KPI scope: no independent population is reported because `offers.xlsx` cannot be reliably linked to valid Gold applications and requisitions.

## Validation results

| Metric | Result | Control | Status |
| --- | ---: | ---: | --- |
| Unique people | 560 | 560 | PASS |
| Applications at Offer on 2026-03-31 | 32 | 32 | PASS |
| Median time to hire, days | 58 | 58 | PASS |
| Engineering annual offered salary, INR | unavailable | 200,700,000 | NOT_INDEPENDENTLY_CALCULABLE |
| Offer acceptance rate, percent | unavailable | 51.2 | NOT_INDEPENDENTLY_CALCULABLE |

## Known data-quality issues

There are 23 applications whose requisition IDs do not exist in `requisitions.json`; these are excluded by the control-total rule. There are also 9 interview records whose application IDs are not present in the application extract, and those records are excluded from the clean interview table.

The Gold layer contains 1,427 valid applications, 4,677 valid stage events, and 1,242 valid interviews. The date dimension contains 330 dates. All 33 Gold integrity checks pass.

The workbook contains 421 offer rows with application IDs, but it has no `req_id` or `candidate_id`. Its department field therefore cannot be independently reconciled to requisitions. For reference only, workbook-only arithmetic gives an Engineering salary sum of `20,330,000,000 INR` and an acceptance rate of `52.1212%` across 330 decided offers. Those values are not treated as validated results and are not used to overwrite the supplied controls.
