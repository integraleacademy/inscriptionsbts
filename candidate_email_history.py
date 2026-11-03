"""Read the archived outgoing mail for one student's dossier."""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from branded_email import email_plain_text
from person_names import person_name


def archived_body(html):
    # Admission messages can contain one-time personal access or signature links.
    return re.sub(r'https?://[^\s<>)]+', '[lien personnel masqué]', email_plain_text(html))


def history(conn, row):
    entries = []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def add(when, subject, source, recipient='', body='', files=()):
        try:
            stamp = datetime.fromisoformat(str(when).replace('Z','+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(ZoneInfo('Europe/Paris'))
        except (ValueError, OverflowError):
            stamp = None
        entries.append(dict(order=stamp.timestamp() if stamp else 0, date=stamp.strftime('%d/%m/%Y à %H:%M') if stamp else 'Date inconnue',
                            subject=subject, source=source, recipient=recipient, body=body, files=files))

    titles = {'accuse_reception':'Accusé de réception de la pré-inscription',
              'inscription_confirmee':'Inscription confirmée', 'reconfirmation_validee':'Reconfirmation validée'}
    for event in conn.execute("""SELECT type,payload,created_at FROM logs WHERE (candidat_id=? OR cid=?)
            AND type IN ('MAIL_ENVOYE','RELANCE_ENVOYEE')""",(row['id'],row['id'])):
        raw = event['payload'] or ''
        if event['type']=='RELANCE_ENVOYEE':
            found = re.search(r'mail_id:\s*([^ /]+)', raw)
            if found and found[1].lower() not in ('false','none','null'):
                add(event['created_at'],'Relance de la candidature validée','Relance')
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        data = data if isinstance(data,dict) else {}
        label = str(data.get('type') or '')
        add(event['created_at'],data.get('objet') or titles.get(label) or label.replace('_',' ').capitalize() or 'E-mail',
            'Dossier étudiant',data.get('destinataire'),data.get('message'),data.get('pieces_jointes'))

    email = (row.get('email') or '').strip().lower()
    name = person_name(row['nom'],row['prenom']).casefold()
    if 'school_message_recipients' in tables:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(school_message_recipients)')}
        cid = 'r.candidate_id' if 'candidate_id' in columns else 'NULL'
        for item in conn.execute(f"""SELECT r.recipient,r.name,r.updated_at,m.subject,m.body,{cid} AS owner
                FROM school_message_recipients r JOIN school_messages m ON m.id=r.message_id
                WHERE r.kind='Étudiant' AND r.status='sent' AND m.channel='email'
                AND ({cid}=? OR ({cid} IS NULL AND lower(trim(r.recipient))=?))""",(row['id'],email)):
            if not item['owner'] and item['name'].strip().casefold() != name:
                continue
            add(datetime.fromtimestamp(item['updated_at'], timezone.utc), item['subject'],'Envoi groupé',item['recipient'],item['body'])
    if email and 'parcoursup_candidats' in tables:
        titles = {'mail':'Votre candidature Parcoursup', 'rectificatif_presentiel':'Rectificatif de la candidature en présentiel',
                  'relance_manuelle':'Relance de la candidature Parcoursup'}
        for person in conn.execute('SELECT nom,prenom,logs FROM parcoursup_candidats WHERE lower(trim(email))=?',(email,)):
            if person_name(person['nom'],person['prenom']).casefold() != name:
                continue
            try:
                events = json.loads(person['logs'] or '[]')
            except ValueError:
                continue
            for event in events if isinstance(events,list) else ():
                if isinstance(event,dict) and event.get('type') in titles:
                    add(event.get('date'), titles[event['type']], 'Parcoursup', event.get('dest') or email)
    return sorted(entries,key=lambda entry:entry['order'],reverse=True)
