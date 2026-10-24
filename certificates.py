"""Personalise legacy Word templates without changing their run formatting."""
import re

from docx.oxml.ns import qn


def _replace(paragraph, replacements):
    nodes = list(paragraph.iter(qn("w:t")))
    for old, new in replacements.items():
        text = "".join(node.text or "" for node in nodes)
        # Right-to-left edits preserve the offsets of earlier matches, including
        # placeholders Word has split over several formatted runs.
        for match in reversed(list(re.finditer(re.escape(old), text))):
            start, end = match.span()
            offset = 0
            inserted = False
            for node in nodes:
                value = node.text or ""
                left, right = offset, offset + len(value)
                offset = right
                if right <= start or left >= end:
                    continue
                prefix = value[:max(0, start - left)]
                suffix = value[max(0, end - left):]
                node.text = prefix + (str(new) if not inserted else "") + suffix
                node.set(qn("xml:space"), "preserve")
                inserted = True


def personalize_certificate(doc, replacements, year):
    parts = [doc.part, *[rel.target_part for rel in doc.part.rels.values()
                        if not rel.is_external and hasattr(rel.target_part, "element")]]
    for part in parts:
        for paragraph in part.element.iter(qn("w:p")):
            if year >= 2027:
                # Apply template years before inserting the actual issue date.
                _replace(paragraph, {"2026": str(year), "2028": str(year + 2)})
                text = "".join(node.text or "" for node in paragraph.iter(qn("w:t")))
                if "6000€" in text:
                    obsolete = "et n'hésitez pas à mettre en avant l'aide de 6000€ que verse l’État à toute entreprise qui recrute un alternant avant le 31 décembre 2025."
                    _replace(paragraph, {obsolete: "notre équipe peut accompagner l’entreprise dans les démarches liées au contrat d’apprentissage."})
            _replace(paragraph, replacements)
