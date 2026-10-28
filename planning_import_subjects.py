"""Catalogue choices and annual allocations created with the imported courses."""
import secrets

import planning as p
import subject_catalog


PREFIX = 'catalog:'


def choices(conn, promotion, period):
    prepared = p._subjects(conn, promotion['id'], period['id'])
    linked = {item['catalog_subject_id'] for item in prepared}
    available = [dict(id=PREFIX + item['id'], catalog_subject_id=item['id'],
                      name=item['name'], prepare_on_import=True,
                      planned_hours=subject_catalog.annual_hours(conn, item['id'], promotion, period))
                 for item in subject_catalog.subjects(conn, promotion['bts']) if item['id'] not in linked]
    return prepared + available


def save(conn, item):
    conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)',
                 tuple(item[k] for k in ('id', 'promotion_id', 'name', 'trainer_id', 'color', 'planned_hours')))
    subject_catalog.link_allocation(conn, item['id'], item['catalog_subject_id'])
    conn.execute('INSERT INTO planning_subject_periods VALUES(?,?)', (item['id'], item['period_id']))


def resolve(conn, promotion, period, choice, trainer_id, hours, preparations, allowed_preparations=None):
    """Stage a missing allocation inside review's rollback-only savepoint.

    Reuse a concurrently prepared subject, including on a repeated submission.
    Its existing teacher and budget always take precedence and are never changed.
    """
    if not choice.startswith(PREFIX):
        return choice
    catalog_id = choice[len(PREFIX):]
    master = subject_catalog.available(conn, catalog_id, promotion['bts'])
    existing = conn.execute('''SELECT s.id FROM planning_subjects s
        JOIN planning_subject_catalog_links l ON l.planning_subject_id=s.id
        JOIN planning_subject_periods y ON y.subject_id=s.id
        WHERE s.promotion_id=? AND y.period_id=? AND l.subject_id=?''',
        (promotion['id'], period['id'], catalog_id)).fetchone()
    if existing:
        return existing['id']
    if allowed_preparations is not None and choice not in allowed_preparations:
        raise p.PlanningError('La préparation de cette matière a été supprimée. Vérifiez à nouveau les cours avant d’importer.', status=409)
    value = hours.get(choice, subject_catalog.annual_hours(conn, catalog_id, promotion, period))
    if value is None or value == '':
        raise p.PlanningError('Renseignez le volume annuel de « ' + master['name'] + ' » dans les correspondances de l’import.')
    item = dict(id=secrets.token_urlsafe(24), promotion_id=promotion['id'], period_id=period['id'],
                catalog_subject_id=catalog_id, name=master['name'], color=master['color'],
                trainer_id=trainer_id, planned_hours=p._annual_hours(value))
    save(conn, item)
    preparations[item['id']] = item
    return item['id']
