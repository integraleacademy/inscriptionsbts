"""One-off school events, with ordinary resource checks but no subject budget."""


def build(conn, data):
    from planning import PlanningError, _promotion, _text, _iso, _minutes, _clock, _has_table
    promotion = _promotion(conn, data.get('promotion_id'), ready=True)
    title = _text(data.get('title', ''), 'le nom de l’événement', 160, True)
    trainer = data.get('trainer_id') or ''
    if not isinstance(trainer, str):
        raise PlanningError('Choisissez un intervenant valide.')
    if trainer and (not _has_table(conn, 'trainers') or not conn.execute('''SELECT 1 FROM trainers t
        JOIN trainer_promotions p ON p.trainer_id=t.id WHERE t.id=? AND t.active=1 AND p.promotion_id=?''',
        (trainer, promotion['id'])).fetchone()):
        raise PlanningError('Choisissez un intervenant actif affecté à cette promotion.')
    room = data.get('room_id') or None
    if room and (not isinstance(room, str) or not conn.execute('SELECT 1 FROM planning_rooms WHERE id=? AND active=1', (room,)).fetchone()):
        raise PlanningError('Choisissez une salle active.')
    if data.get('shared'):
        raise PlanningError('Cet événement concerne une seule promotion.')
    day = _iso(data.get('date')).isoformat()
    start, end = _minutes(data.get('start')), _minutes(data.get('end'), True)
    if end <= start:
        raise PlanningError('L’heure de fin doit être postérieure à l’heure de début.')
    group = dict(promotion_id=promotion['id'], subject_id='', promotion_name=promotion['nom'], subject_name=title, color='#7c3aed')
    return dict(kind='event', promotion_id=promotion['id'], subject_id='', trainer_id=trainer, room_id=room,
                date=day, start=_clock(start), end=_clock(end), start_min=start, end_min=end, title=title,
                zoom_url='', groups=[group], shared=[], promotion_ids=[promotion['id']], is_shared=False)
