"""Local apprenticeship dossiers. The official V2 schema is bundled, never fetched at runtime."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re

SCHEMAS = json.loads((Path(__file__).parent / 'apprenticeship_assets/convergence-v2.json').read_text())
# The published schema requires employeurV2 but defines employeur; the official POST example uses employeur.
SCHEMAS['CerfaDossierV2']['required'] = [x.replace('employeurV2', 'employeur') for x in SCHEMAS['CerfaDossierV2']['required']]
PROVIDERS = {'akto':'AKTO', 'opcommerce':'L’Opcommerce', 'ep':'OPCO EP', 'mobilites':'OPCO Mobilités'}
STATES = {'draft':'À compléter', 'ready':'Prêt à transmettre', 'sending':'Transmission en cours',
          'sent':'Transmis à l’OPCO', 'accepted':'Engagé', 'pending':'En instruction', 'refused':'Refusé',
          'uncertain':'Transmission à vérifier', 'partial':'Pièce CERFA à transmettre', 'cancelled':'Annulé',
          'broken':'Rompu', 'completed':'Soldé', 'archived':'Archivé'}
REMOTE_STATES = {'TRANSMIS':'sent', 'EN_COURS_INSTRUCTION':'pending', 'ENGAGE':'accepted', 'REFUSE':'refused',
                 'ANNULE':'cancelled', 'RUPTURE':'broken', 'RUTPURE':'broken', 'SOLDE':'completed'}
LABELS = {
 'nom':'Nom de naissance', 'nomUsage':'Nom d’usage', 'prenom':'Prénom', 'sexe':'Sexe', 'nationalite':'Nationalité',
 'dateNaissance':'Date de naissance', 'departementNaissance':'Département de naissance', 'communeNaissance':'Commune de naissance',
 'nir':'N° de sécurité sociale (13 caractères, sans la clé)', 'regimeSocial':'Régime social', 'handicap':'Reconnaissance RQTH',
 'droitsRqthExtensionBOE':'Droits RQTH : extension BOE', 'droitsRqthEquivalenceJeune':'Droits RQTH : équivalence jeune',
 'situationAvantContrat':'Situation avant le contrat', 'diplome':'Diplôme le plus élevé obtenu',
 'derniereClasse':'Dernière classe / année suivie', 'diplomePrepare':'Dernier diplôme préparé',
 'intituleDiplomePrepare':'Intitulé du dernier diplôme préparé', 'telephone':'Téléphone', 'courriel':'E-mail',
 'adresse1':'Adresse', 'adresse2':'Complément d’adresse', 'codePostal':'Code postal', 'commune':'Commune', 'codePays':'Code pays INSEE (France : 99100)',
 'inscriptionSportifDeHautNiveau':'Sportif de haut niveau', 'projetCreationRepriseEntreprise':'Projet de création / reprise d’entreprise',
 'denomination':'Raison sociale', 'siret':'SIRET', 'naf':'Code APE / NAF', 'nombreDeSalaries':'Effectif total',
 'codeIdcc':'Code IDCC', 'codeIdccConventionAppliquee':'IDCC de la convention appliquée', 'libelleIdcc':'Convention collective',
 'typeEmployeur':'Type d’employeur', 'employeurSpecifique':'Employeur spécifique', 'caisseComplementaire':'Caisse de retraite complémentaire',
 'regimeSpecifique':'Régime spécifique d’assurance chômage (public)', 'attestationEligibilite':'L’employeur atteste l’éligibilité du maître d’apprentissage',
 'attestationPieces':'L’employeur atteste détenir les pièces justificatives', 'emploiOccupe':'Emploi occupé',
 'intituleDiplomeObtenu':'Diplôme / titre obtenu', 'niveauDiplomeObtenu':'Niveau du diplôme obtenu',
 'modeContractuel':'Nature du contrat', 'typeContratApp':'Type de contrat / avenant', 'numeroContratPrecedent':'N° DECA du contrat précédent',
 'noContrat':'N° DECA', 'noAvenant':'N° avenant', 'dateDebutContrat':'Début du contrat', 'dateFinContrat':'Fin du contrat',
 'dateFormationPratiqueEmployeur':'Début de la formation pratique en entreprise', 'dateConclusion':'Date de signature du contrat',
 'dateRupture':'Date de rupture', 'lieuSignatureContrat':'Lieu de signature', 'typeDerogation':'Dérogation',
 'dureeTravailHebdoHeures':'Durée hebdomadaire : heures', 'dureeTravailHebdoMinutes':'Durée hebdomadaire : minutes',
 'travailRisque':'Machines dangereuses / risques particuliers', 'salaireEmbauche':'Salaire brut mensuel à l’embauche (€)',
 'avantageNourriture':'Avantage nourriture (€ / repas)', 'avantageLogement':'Avantage logement (€ / mois)',
 'autreAvantageEnNature':'Autres avantages en nature', 'motifReductionDureeContrat':'Motif de réduction de durée',
 'anneeFormationEntreeContrat':'Année du cycle à l’entrée', 'dateDebut':'Début', 'dateFin':'Fin', 'taux':'Rémunération (%)',
 'typeSalaire':'Base du salaire', 'ordre':'Période (1.1, 1.2, 2.1…)', 'rncp':'Code RNCP', 'codeDiplome':'Code diplôme',
 'typeDiplome':'Diplôme / titre visé', 'intituleQualification':'Intitulé de la formation', 'dateDebutFormation':'Début de formation',
 'dateFinFormation':'Fin des épreuves / examens', 'dureeFormation':'Volume de formation (heures)',
 'nombreHeuresEnDistanciel':'Dont heures à distance', 'formationInterne':'CFA d’entreprise', 'uaiCfa':'UAI',
 'lieuFormationIdentique':'Formation au même lieu que le CFA responsable', 'coutTotalPedagogieCFA':'Coût pédagogique total (€)',
 'nombreRepasTotaux':'Nombre total de repas', 'nombreHebergementTotaux':'Nombre total de nuitées',
 'montantPremierEquipement':'Premier équipement (€)', 'mentionMobiliteInternationale':'Mobilité internationale',
 'montantMobiliteInternationale':'Mobilité internationale (€)', 'accompagnementDROM':'Accompagnement DROM',
 'montantAccompagnementDROM':'Accompagnement DROM (€)', 'mandatEmployeur':'Mandat de l’employeur accordé au CFA',
 'dateSignature':'Date de signature de la convention', 'attestationConventionSigneeEntreprise':'Convention signée par l’entreprise',
 'attestationConventionSigneeCFA':'Convention signée par le CFA', 'attestationConventionSignatureProbante':'Signature probante de la convention',
 'attestationConventionConformeJSON':'La convention signée correspond aux informations du dossier',
 'CERFASignatureProbante':'Signature probante du CERFA', 'CERFAAttestationExactitudeInformations':'Informations du CERFA vérifiées et exactes',
 'CERFAAttestationConformiteContratApprenti':'Contrat conforme à la situation de l’apprenti', 'CERFAAttestationSigneCFA':'CERFA visé par le CFA',
 'CERFAAttestationSigneEmployeurApprenti':'CERFA signé par l’employeur, l’apprenti et son représentant si nécessaire',
 'CERFAEngagementDispositionPieces':'Pièces justificatives tenues à disposition',
}
for n in range(1,5): LABELS[f'montantRQTHAnnee{n}'] = f'Majoration RQTH année {n} (€)'

GROUPS = [
 ('student','Identité et coordonnées','cerfa.apprenti','ApprentiV2'),
 ('student','Représentant légal · si nécessaire','cerfa.apprenti.responsableLegal','ResponsableLegalV2'),
 ('student','Formation préparée','cerfa.formation','FormationV2'),
 ('student','CFA responsable','cerfa.organismeFormation','OrganismeFormationV2'),
 ('student','Lieu principal de formation · si différent','cerfa.organismeFormationLieuFormationPrincipal','OrganismeFormationLieuFormationPrincipalV2'),
 ('contract','Termes et calendrier du contrat','cerfa.contrat','ContratV2'),
 ('company','Entreprise et contact','cerfa.employeur','EmployeurCerfaV2'),
 ('company','Maître d’apprentissage','cerfa.maitre1','MaitreApprentissageV2'),
 ('company','Deuxième maître d’apprentissage · facultatif','cerfa.maitre2','MaitreApprentissageV2'),
 ('management','Financement et frais annexes','convention.couts','CoutsConventionV2'),
 ('management','Convention : mandat et signatures','convention','ConventionDossierV2'),
 ('management','CERFA : attestations avant transmission','cerfa','CerfaDossierV2'),
]

def now(): return datetime.now(timezone.utc).isoformat()

def resolve(s): return SCHEMAS[s['$ref'].split('/')[-1]] if '$ref' in s else s

def at(data,path,default=None):
    for key in path.split('.'):
        if not isinstance(data,dict) or key not in data:return default
        data=data[key]
    return data

def put(data,path,value):
    parts=path.split('.')
    for key in parts[:-1]:data=data.setdefault(key,{})
    data[parts[-1]]=value

def options(s):
    description=s.get('description','')
    labels=dict(re.findall(r'(?:<br\s*/?>)\s*(\w+)\s*:\s*([^<\r\n]+)',description))
    return [{'value':x,'label':f'{x} · {labels.get(str(x),str(x))}' if str(x) in labels else str(x)} for x in s.get('enum',[]) if x is not None]

def fields(schema,path):
    result=[]
    for key,raw in SCHEMAS[schema].get('properties',{}).items():
        s=resolve(raw)
        if (s.get('deprecated') or key in ('responsableLegal','maitre2','organismeFormationLieuFormationPrincipal',
            'numeroExterne','numeroInterne','numeroDeca','etat','commentaireEtat','versionCERFA')):continue
        if s.get('type')=='array':continue
        if s.get('type')=='object' or s.get('properties'):
            if key=='adresse':result.extend(fields(raw['$ref'].split('/')[-1],path+'.'+key))
            continue
        typ='select' if s.get('enum') else 'boolean' if s.get('type')=='boolean' else 'date' if s.get('format') in ('date','date-time') else 'number' if s.get('type') in ('integer','number') else 'email' if s.get('format')=='email' else 'text'
        result.append(dict(path=path+'.'+key,label=LABELS.get(key,key),type=typ,options=options(s),
                           required=key in SCHEMAS[schema].get('required',[]),maxLength=s.get('maxLength',500),
                           integer=s.get('type')=='integer' or s.get('format') in ('int','integer')))
    return result

FORM_GROUPS=[dict(tab=t,title=title,path=p,fields=fields(s,p)) for t,title,p,s in GROUPS]

def validate(payload,complete=True):
    errors=[]
    def issue(path,msg):errors.append({'path':path,'label':LABELS.get(path.split('.')[-1],path),'message':msg})
    def walk(value,s,path):
        s=resolve(s)
        if value is None:
            if not s.get('nullable'):issue(path,'Valeur attendue.')
            return
        typ=s.get('type')
        if typ=='object' or s.get('properties'):
            if not isinstance(value,dict):issue(path,'Objet attendu.');return
            if complete:
                for key in s.get('required',[]):
                    if key not in value or value[key] in (None,''):
                        child=s.get('properties',{}).get(key,{})
                        if resolve(child).get('properties'):walk({},child,path+'.'+key)
                        else:issue(path+'.'+key,'À renseigner.')
            for key,val in value.items():
                if key not in s.get('properties',{}):issue(path+'.'+key,'Champ non reconnu.')
                else:walk(val,s['properties'][key],path+'.'+key)
        elif typ=='array':
            if not isinstance(value,list) or len(value)>8:issue(path,'Huit périodes maximum.');return
            if complete and not value:issue(path,'Ajoutez au moins une période.')
            for i,val in enumerate(value):walk(val,s['items'],path+f'.{i}')
        elif typ=='boolean':
            if type(value) is not bool:issue(path,'Choisissez oui ou non.')
        elif typ in ('number','integer'):
            if type(value) not in (int,float) or not math.isfinite(value) or value<0 or value>100000000:issue(path,'Nombre positif attendu.')
            elif (typ=='integer' or s.get('format') in ('int','integer')) and int(value)!=value:issue(path,'Nombre entier attendu.')
        elif typ=='string':
            if not isinstance(value,str):issue(path,'Texte attendu.');return
            if len(value)>s.get('maxLength',2000):issue(path,'Texte trop long.')
            if s.get('pattern') and not re.fullmatch(s['pattern'],value):issue(path,'Format à vérifier.')
            if s.get('format') in ('date','date-time'):
                try:date.fromisoformat(value[:10])
                except ValueError:issue(path,'Date invalide.')
            if s.get('format')=='email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):issue(path,'E-mail invalide.')
        if s.get('enum') and value not in s['enum']:issue(path,'Choisissez une valeur proposée.')
    walk(payload,SCHEMAS['PostDossierRequestV2'],'')
    for section,start,end in [('cerfa.contrat','dateDebutContrat','dateFinContrat'),('cerfa.formation','dateDebutFormation','dateFinFormation')]:
        a,b=at(payload,section+'.'+start),at(payload,section+'.'+end)
        if isinstance(a,str) and isinstance(b,str) and a and b and a>b:issue(section+'.'+end,'La fin doit suivre le début.')
    hours=at(payload,'cerfa.formation.dureeFormation',0);remote=at(payload,'cerfa.formation.nombreHeuresEnDistanciel',0)
    if isinstance(hours,(int,float)) and isinstance(remote,(int,float)) and remote>hours:issue('cerfa.formation.nombreHeuresEnDistanciel','Ne peut dépasser le volume total.')
    for key,limit in [('dureeTravailHebdoHeures',50),('dureeTravailHebdoMinutes',59)]:
        v=at(payload,'cerfa.contrat.'+key)
        if isinstance(v,(int,float)) and v>limit:issue('cerfa.contrat.'+key,f'Maximum : {limit}.')
    if complete:
        birth=at(payload,'cerfa.apprenti.dateNaissance');start=at(payload,'cerfa.contrat.dateDebutContrat')
        if birth and start:
            try:
                b,d=date.fromisoformat(birth[:10]),date.fromisoformat(start[:10])
                age=d.year-b.year-((d.month,d.day)<(b.month,b.day))
                if age<18 and not at(payload,'cerfa.apprenti.responsableLegal'):issue('cerfa.apprenti.responsableLegal','Complétez le représentant légal de l’apprenti mineur.')
            except (ValueError,TypeError):pass
        if at(payload,'cerfa.organismeFormation.lieuFormationIdentique') is False and not at(payload,'cerfa.organismeFormationLieuFormationPrincipal'):
            issue('cerfa.organismeFormationLieuFormationPrincipal','Complétez le lieu principal de formation.')
        kind=at(payload,'cerfa.contrat.typeContratApp',11)
        if isinstance(kind,int) and kind!=11 and not at(payload,'cerfa.contrat.numeroContratPrecedent'):issue('cerfa.contrat.numeroContratPrecedent','Le contrat précédent est nécessaire.')
        periods=at(payload,'cerfa.contrat.remunerationsAnnuelles',[])
        previous=None;orders=set()
        for i,p in enumerate(periods if isinstance(periods,list) else []):
            if not isinstance(p,dict):continue
            a,b=p.get('dateDebut',''),p.get('dateFin','')
            if not isinstance(a,str) or not isinstance(b,str):continue
            if a>b or (previous and a<=previous):issue(f'cerfa.contrat.remunerationsAnnuelles.{i}','Périodes inversées ou qui se chevauchent.')
            if str(p.get('ordre')) in orders or not re.fullmatch(r'[1-4]\.[12]',str(p.get('ordre',''))):issue(f'cerfa.contrat.remunerationsAnnuelles.{i}.ordre','Ordre unique entre 1.1 et 4.2 attendu.')
            orders.add(str(p.get('ordre')));previous=b
    for e in errors:e['path']=e['path'].lstrip('.')
    return errors

def completion(payload):
    def count(value,s):
        s=resolve(s)
        if s.get('properties'):
            value=value if isinstance(value,dict) else {}
            return sum(count(value.get(k),v) for k,v in s['properties'].items() if k in s.get('required',[]) or (k in value and resolve(v).get('properties')))
        if s.get('type')=='array' and isinstance(value,list) and value:return sum(count(v,s['items']) for v in value)
        return 1
    return max(0,round(100*(1-len(validate(payload))/max(1,count(payload,SCHEMAS['PostDossierRequestV2'])))))

def clean_payload(payload):
    """Omit unfilled controls, retaining explicit false and zero; whitelist with validation."""
    if not isinstance(payload,dict):raise ValueError('Dossier invalide.')
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if v is not None and v!='' and v!={}}
        if isinstance(value,list):return [clean(v) for v in value]
        return value.strip() if isinstance(value,str) else value
    result=clean(payload)
    if not isinstance(result.setdefault('cerfa',{}),dict):raise ValueError('Le contenu du CERFA est invalide.')
    result['cerfa']['versionCERFA']='10103*14'
    return result

def document_content(payload,details):
    """Attestations recorded after signature do not change the document itself."""
    p=deepcopy(payload)
    for key in list(p.get('cerfa',{})):
        if key.startswith('CERFA'):p['cerfa'].pop(key)
    for key in list(p.get('convention',{})):
        if key.startswith('attestationConvention'):p['convention'].pop(key)
    return p,{k:v for k,v in details.items() if k not in ('owner','notes','promotion','job_title','missions')}

def project_cerfa(raw):
    """Whitelist OPCO fields, omit identifiers/unknown financial details, normalize dates."""
    def project(value,s):
        s=resolve(s)
        if isinstance(value,dict):return {k:project(v,s['properties'][k]) for k,v in value.items() if k in s.get('properties',{}) and k not in ('numeroInterne','numeroExterne','numeroDeca','etat','commentaireEtat') and v is not None and v!=''}
        if isinstance(value,list):return [project(v,s.get('items',{})) for v in value[:8]]
        if s.get('format')=='date-time' and isinstance(value,str):return value[:10]
        return value
    return project(raw,SCHEMAS['CerfaDossierV2'])

def wire_payload(payload):
    result=deepcopy(payload)
    def walk(value,s):
        s=resolve(s)
        if isinstance(value,dict):return {k:walk(v,s.get('properties',{}).get(k,{})) for k,v in value.items()}
        if isinstance(value,list):return [walk(v,s.get('items',{})) for v in value]
        if s.get('format')=='date-time' and isinstance(value,str) and len(value)==10:return value+'T00:00:00+00:00'
        return value
    return walk(result,SCHEMAS['PostDossierRequestV2'])

def seed(person,promotion=None,company=None):
    person=dict(person);promotion=promotion or {};company=company or {}
    apprentice={key:person.get(source) for key,source in {'nom':'nom','nomUsage':'nom','prenom':'prenom','dateNaissance':'date_naissance',
        'communeNaissance':'ville_naissance','courriel':'email','telephone':'tel'}.items()}
    if person.get('num_secu'):apprentice['nir']=re.sub(r'\s','',person['num_secu']).upper()[:13]
    if person.get('sexe') in ('Homme','Femme'):apprentice['sexe']='M' if person['sexe']=='Homme' else 'F'
    apprentice['adresse']={'adresse1':person.get('adresse'),'codePostal':person.get('cp'),'commune':person.get('ville'),'codePays':'99100'}
    formation={'intituleQualification':promotion.get('nom') or person.get('bts'),'dateDebutFormation':promotion.get('date_debut'),'dateFinFormation':promotion.get('date_fin')}
    data={'cerfa':{'apprenti':apprentice,'formation':formation,'contrat':{},'employeur':{},'maitre1':{},
      'organismeFormation':{'denomination':'INTEGRALE SECURITE FORMATIONS','uaiCfa':'0756548K' if person.get('mode')=='distanciel' else '0831774C',
          'adresse':{'adresse1':'54 chemin du Carreou','codePostal':'83480','commune':'Puget-sur-Argens','codePays':'99100'}}},'convention':{'couts':{}}}
    for key,source in {'denomination':'name','siret':'siret','courriel':'email','telephone':'phone','naf':'activity_code'}.items():
        if company.get(source):data['cerfa']['employeur'][key]=company[source]
    if company.get('address'):data['cerfa']['employeur']['adresse']={'adresse1':company['address'],'codePostal':company.get('postal_code'),'commune':company.get('city'),'codePays':'99100'}
    return clean_payload(data)
