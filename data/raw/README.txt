NORTHBEAM PARTNERS — ATS EXTRACT
================================

A raw export from an applicant tracking system in use since September 2025.

  candidates.csv      One row per candidate record.
  applications.csv    One row per application. Note current_stage is a denormalised
                      convenience column maintained by the application.
  stage_events.csv    Every stage transition recorded against an application.
  requisitions.json   Open and closed roles.
  users.json          Recruiters, hiring managers, admins.
  interviews.json     Scheduled interviews and outcomes.
  offers.xlsx         Offers extended, with salary and decision.

CONTROL_TOTALS.txt holds five figures your data layer must reproduce.

This export has not been cleaned. It is representative of what arrives from a
production system that has been running for a while.
