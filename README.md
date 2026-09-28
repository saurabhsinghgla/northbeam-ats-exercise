# ATS Analytics Data Engineering Take-Home

This project builds a reproducible applicant-tracking-system data layer and concise analytics report from an unclean ATS export. Raw source files are preserved unchanged, malformed offer data is reported as a limitation, and calculated results are checked against the supplied control totals.

## Architecture

The repository follows a simple medallion structure:

```text
RAW -> CLEAN -> GOLD -> measures and report
```

- **RAW** (`data/raw/`): authoritative source CSV, JSON, and XLSX exports. These files are immutable inputs.
- **CLEAN** (`data/clean/`): normalized source-aligned tables, valid requisition joins, propagated person IDs, and filtered records.
- **GOLD** (`data/gold/`): dimensional model with conformed dimensions and facts ready for analysis.
- **Measures/report** (`data/output/`): validated business measures, supporting datasets, validation results, diagnostics, and the generated HTML report.

## Gold Model

Dimensions:

- `dim_person`: one row per deduplicated person.
- `dim_requisition`: one row per requisition.
- `dim_user`: one row per ATS user.
- `dim_date`: one row per calendar date used by Gold facts.

Facts:

- `fact_application`: one row per valid application.
- `fact_stage_event`: one row per valid stage-transition event.
- `fact_interview`: one row per valid interview.

## Business Measures

- **Time to Hire:** calculated as calendar days from application date to the first authoritative Hired event. The result is 58 days across 97 application-level records for hires dated 2026-01-01 through 2026-06-30.
- **Offer Acceptance Rate:** `NOT_INDEPENDENTLY_CALCULABLE` because `offers.xlsx` cannot be reliably linked to valid Gold applications and requisitions.
- **Engineering Annual Offered Salary:** `NOT_INDEPENDENTLY_CALCULABLE` because the malformed workbook has no reliable requisition identifier. No scaling factor or manual override is used.

## Run

From the repository root:

```bash
python scripts/build_data_layer.py
```

The generated report is [data/output/ats_report.html](data/output/ats_report.html).

Validation outputs are available in:

- [data/output/validation.csv](data/output/validation.csv): supplied control totals.
- [data/output/gold_validation.csv](data/output/gold_validation.csv): Gold integrity checks.
- [data/output/measure_validation.csv](data/output/measure_validation.csv): business-measure validation.
- [data/output/data_quality.json](data/output/data_quality.json): source counts and data-quality diagnostics.

## Validation Summary

- Gold validation: 33 checks, 0 failures.
- Median Time to Hire: 58 days.
- Application-level Time to Hire records: 97.
- Unique people: 560.
- Applications at Offer stage on 2026-03-31: 32.

## Known Limitations

- 23 applications reference requisitions that do not exist in the requisition source and are excluded from valid Gold populations.
- 9 interviews reference missing applications and are excluded from the clean interview table.
- `offers.xlsx` contains no reliable `req_id` or `candidate_id` linkage. Offer Acceptance Rate and Engineering Annual Offered Salary are therefore not independently calculable.
- No artificial mappings, fabricated offer values, scaling factors, or control-total overrides are used.

See [docs/data-layer.md](docs/data-layer.md) for source authority, transformations, table grains, measure definitions, report scopes, and detailed limitations.
