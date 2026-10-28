"""Recognize the confirmed first-year CI/PI English and expression sessions."""
import planning as p
import planning_years
from planning_import_pdf import normal
from subject_catalog import study_year


def family(name):
    name = normal(name)
    if name in {'anglais', 'langue vivante etrangere', 'langue vivante etrangere anglaise'}:
        return 'english'
    if name == 'culture generale et expression':
        return 'expression'
    return None


def find(conn, course, promotion, period, existing):
    """A unique physical session, with identical hours and teacher, can be joined."""
    subject = family(course['groups'][0]['subject_name'])
    partner_bts = {'CI': 'PI', 'PI': 'CI'}.get(promotion['bts'])
    if not subject or not partner_bts or study_year(promotion, period) != 1:
        return None
    matches = []
    for other in existing:
        groups = p._groups(other)
        if (other.get('kind', 'course') != 'course' or len(groups) != 1 or
                any(other[k] != course[k] for k in ('date', 'start_min', 'end_min', 'trainer_id')) or
                family(groups[0]['subject_name']) != subject):
            continue
        partner = p._promotion(conn, groups[0]['promotion_id'])
        allocation = planning_years.allocation(conn, groups[0]['subject_id'])
        if (partner['bts'] == partner_bts and partner['active'] and allocation and
                study_year(partner, allocation) == 1 and planning_years.contains(allocation, course['date']) and
                promotion.get('rentree_annee') is not None and
                partner.get('rentree_annee') == promotion['rentree_annee'] and
                allocation['start_date'][:4] == period['start_date'][:4]):
            matches.append(other)
    return matches[0] if len(matches) == 1 else None
