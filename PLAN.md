# PLAN

Every slice in this plan is built. S0, SR, S1, S2 and S4 are on the primary branch; S3 is on `guid-candidate-ids` and merges after the take. Open work, the merge order and the live findings live in `docs/STATUS.md`. Built behaviour is described in the README and owned by the code. The designs that were in this file either became code or moved to `docs/process-design.md` ("Designed, not built").

The `guid-candidate-ids` branch deletes this file. Nothing in the docs points at it.

| Slice | What | Where |
|---|---|---|
| S0 | Unanswered agent message limit | `ecb6b4a` |
| SR | Demo reset | `fa74e41`, reworked to close in place on `guid-candidate-ids` |
| S1 | Fixed reply for an unknown number | `9071b79` |
| S2 | Applicant name, opener personalisation, mismatch confirmation | `9b26f09`, review fixes `d45d63b` |
| S3 | Opaque candidate ids, one open conversation per phone, per-phone limits, backfill | `guid-candidate-ids` at `133b2a5` |
| S4 | Applicant file and `screening-admin start-from-file` | `011794f` |
