# Original school certificate templates

The source of truth remains `static/templates/certificat_scolarite_presentiel.docx` and `static/templates/certificat de scolarité 2026.docx`. Do not replace their layout with a new ReportLab design.

`models.pdf` contains the rendered original Word bundles for both modes, all six diplomas, and the legacy/current cohort wording. Shared images and fonts are deduplicated. `manifest.json` identifies each three-page bundle and its variable fields. `certificates.py` fills only the name, issue date and cohort years; course text is rendered by Office to preserve wrapping. PDF previews and mail attachments use the same frozen bytes.

To update a source model, regenerate with `python scripts/build_certificate_templates.py` in a development environment with LibreOffice, python-docx and PyMuPDF installed. Commit the source and regenerated assets together. The source checksums prevent silently serving an outdated PDF after a Word edit. Production needs only pypdf and ReportLab, with no Office subprocess or external conversion service.

The builder sets explicit page starts for the confirmation letter and apprenticeship annex to avoid headings crossing the source footer under different font metrics. All other source wording, images, shading, tables and signature graphics are retained. Existing cohort adjustments in `personalize_certificate` also apply to the PDF.

The bundled Liberation Sans fonts preserve the Word rendering metrics and are distributed under the accompanying SIL Open Font License. After rebuilding, visually check all three pages in both modes and a long student/course name. Run the candidate certificate tests, including original image preservation and preview/attachment equality.
