"""Document guidance, never an automatic decision on an apprentice's rights.

Categories follow the user-supplied Occitanie guide, with the school's common
case of work scheduled during lessons. Historical ICF rules and obsolete leave
durations are deliberately not encoded as current law.
"""
GUIDE_URL = 'https://www.lapprenti.com/upload/docs/droit/Guide_qualification_absences_en_CFA.htm'
LAW_URL = 'https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050/LEGISCTA000006195795/'
REASONS = (
    ('company_work', 'Entreprise', 'Présence en entreprise pendant les cours', 'Planning de l’entreprise indiquant ton nom, les dates et les horaires travaillés correspondant aux cours manqués.'),
    ('illness', 'Santé', 'Maladie ou accident avec arrêt', 'Arrêt de travail ou justificatif médical couvrant la période, sans détail sur le diagnostic.'),
    ('maternity', 'Santé', 'Congé maternité', 'Attestation du congé ou arrêt couvrant la période.'),
    ('paternity', 'Santé', 'Congé paternité ou accueil de l’enfant', 'Attestation des dates du congé.'),
    ('work_medical', 'Santé', 'Visite médicale du travail', 'Convocation ou attestation de présence.'),
    ('legal_summons', 'Convocations', 'Convocation judiciaire, police ou gendarmerie', 'Convocation indiquant la date et les horaires.'),
    ('exam', 'Convocations', 'Convocation à un examen', 'Convocation à l’examen.'),
    ('driving_test', 'Convocations', 'Examen du permis de conduire', 'Convocation à l’épreuve du permis (hors leçons de conduite).'),
    ('theory_test', 'Convocations', 'Examen du code de la route', 'Convocation à l’examen (hors cours de code).'),
    ('tax_summons', 'Convocations', 'Convocation de l’administration fiscale', 'Convocation précisant la date.'),
    ('transport_incident', 'Transports', 'Incident des transports publics', 'Attestation du transporteur avec date, ligne et horaires.'),
    ('transport_strike', 'Transports', 'Grève des transports publics', 'Attestation du transporteur ou document de presse daté.'),
    ('blockade', 'Transports', 'Blocage empêchant le déplacement', 'Justificatif daté de la perturbation ou document de presse.'),
    ('weather', 'Transports', 'Intempéries', 'Avis officiel ou document de presse daté concernant le trajet.'),
    ('marriage', 'Événements familiaux', 'Mariage ou PACS', 'Acte ou attestation de mariage ou de PACS.'),
    ('birth_adoption', 'Événements familiaux', 'Naissance ou adoption', 'Acte ou attestation de naissance ou d’adoption.'),
    ('bereavement', 'Événements familiaux', 'Décès d’un proche', 'Acte de décès et précision du lien familial utile au traitement.'),
    ('firefighter', 'Autres situations', 'Intervention ou formation de sapeur-pompier volontaire', 'Attestation d’intervention ou de formation ; situation examinée par l’équipe.'),
    ('other', 'Autres situations', 'Autre situation à examiner', 'Document expliquant la situation et les dates concernées. Précise le motif dans ton message.'),
)
REASON_MAP = {key: dict(key=key, group=group, label=label, evidence=evidence)
              for key, group, label, evidence in REASONS}
REASON_GROUPS = {}
for reason in REASON_MAP.values():
    REASON_GROUPS.setdefault(reason['group'], []).append(reason)
