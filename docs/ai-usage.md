# AI and Coding-Agent Usage

AI/coding-agent assistance was used as an implementation aid for this take-home exercise. The agent was delegated repository inspection, schema and data-quality profiling, pipeline implementation, Gold-model generation, measure/report generation, documentation drafts, and validation command execution.

Human review remained responsible for the exercise decisions and final acceptance of the work, including source authority, requisition-validity exclusions, person-identity assumptions, measure definitions, control-total interpretation, report scope, and whether generated outputs were suitable for submission.

The work was manually validated by inspecting source schemas and joins, checking generated row counts and output contents, reviewing control-total results, checking Gold referential-integrity results, and confirming that raw-file status remained unchanged. During development, syntax checks caught and led to correction of local code-placement and insertion errors before final execution. The final validation framework reported 33 Gold checks with 0 failures; Time to Hire validated to 58 days across 97 application-level records.

The `offers.xlsx` workbook was deliberately not forced into Gold. It lacks reliable requisition and candidate linkage, so offer acceptance and Engineering salary cannot be independently calculated. No offer identifiers, mappings, statuses, scaling factors, or manually forced control values were invented.

Raw data under `data/raw/` was never modified, deleted, renamed, overwritten, or altered. Generated calculations were compared with the supplied control totals, with unsupported offer controls explicitly reported as `NOT_INDEPENDENTLY_CALCULABLE`.
