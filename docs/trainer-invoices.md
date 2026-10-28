# Trainer invoices: private, monthly, advisory

The trainer accounting tab accepts multiple PDF/PNG/JPEG invoices, submitted one by
one so an invalid file does not discard the batch. Select the service month and
explicitly state whether the configured hourly rates are HT or TTC. Originals are
private attachments under `DATA_DIR/trainer_invoices` (Render persistent disk), not
under `/static`. All endpoints require administrator authentication; mutations also
require the trainer-page CSRF token. Limits: ten selected files, 12 MiB per file,
20 PDF pages, 25 megapixels per image, 200 retained documents per trainer/month and
30 analyses per trainer/hour. Password-protected PDFs are rejected.

The module reuses the encrypted OpenAI settings or `OPENAI_API_KEY` already supported
by the application. `OPENAI_INVOICE_MODEL` optionally overrides `gpt-4.1`. The original
invoice and a minimal course context are sent to the Responses API with `store=false`,
no tools and strict structured outputs. No student records, attendance roster or bank
context are fetched for the prompt; personal data already printed in an uploaded
invoice is necessarily part of the file sent to the provider. The interface discloses
that transfer. Provider data handling remains subject to the account's OpenAI terms.

A synchronous, bounded provider request is made per document (5 s connect / 75 s read
limits). SQLite is never held open for writing during that request. A token-checked
lease prevents concurrent analysis for a trainer and interrupted jobs become retryable
after five minutes. An upload survives provider failure. There is no daemon or external
queue to install, and no request is silently retried at additional API cost.

AI output is treated as untrusted extraction, not as an approval. Deterministic integer
cent calculations check arithmetic, VAT, rates effective at course dates, durations,
periods, duplicate sessions and invoice numbers. Exact matches need local date and time
corroboration. Model-suggested monthly matches are explicitly review-only. Shared
classes are canonical physical sessions, never one charge per promotion. Missing
amounts/rates/hours stay unknown. Fees and credits require manual handling. Foreign
currencies and mixed rate bases cannot produce a falsely comparable euro aggregate.

Reports re-evaluate against the current planning whenever loaded. The original AI
reading, planning snapshot and report are retained per successful analysis. A visible
notice identifies changed planning/rates/teaching evidence. Roll-call completion or
journal entries are only indications, never proof of the trainer's presence. No payment
or accounting validation is performed. Soft-archiving excludes a document from the
monthly check while preserving its original and historical analyses.

Registration happens alongside the existing admin trainer panels in
`register_admin_trainer_planning`. The student/trainer portals never receive invoices,
hourly rates, financial reports or invoice download links.

Tests: `python -m pytest -q tests/test_trainer_invoice_audit.py tests/test_trainer_invoice_routes.py`
and `node --check static/js/trainer-invoices.js`. Provider calls are mocked; the test
suite never consumes production credits or modifies production records.
