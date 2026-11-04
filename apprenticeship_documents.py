"""Official CERFA 10103*14 and a readable training agreement, generated from a revision."""
from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from planning_pdf import _fonts

from apprenticeship_data import at

TEMPLATE=Path(__file__).parent/'apprenticeship_assets/cerfa_10103-14.pdf'

def cerfa_values(data):
    values={}
    def field(n,value,prefix='Zone de texte 8'):
        if value is not None:values[prefix+('' if n==1 else '_'+str(n))]=str(value)
    def dt(start,path):
        value=at(data,path,'')[:10]
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            y,m,d=value.split('-')
            for n,v in zip(range(start,start+3),(d,m,y)):field(n,v,'Zone de texte 21')
    def check(suffix,value):
        if value:values['Case #C3#A0 cocher '+suffix]='/Yes'
    def boolean(yes,no,path):
        value=at(data,path)
        if value is not None:check(yes if value else no,True)
    mapping={
      1:'employeur.denomination',2:'employeur.siret',3:'employeur.typeEmployeur',4:'employeur.employeurSpecifique',
      5:'employeur.nombreDeSalaries',6:'employeur.codeIdccConventionAppliquee',7:'employeur.naf',8:'employeur.adresse.adresse2',
      9:'employeur.adresse.codePostal',10:'employeur.adresse.commune',11:'employeur.telephone',12:'employeur.courriel',
      15:'apprenti.nom',16:'apprenti.nomUsage',17:'apprenti.prenom',18:'apprenti.nir',21:'apprenti.adresse.adresse2',
      22:'apprenti.adresse.codePostal',23:'apprenti.adresse.commune',24:'apprenti.telephone',25:'apprenti.courriel',
      26:'apprenti.departementNaissance',27:'apprenti.communeNaissance',28:'apprenti.situationAvantContrat',
      29:'apprenti.diplomePrepare',30:'apprenti.derniereClasse',31:'apprenti.intituleDiplomePrepare',32:'apprenti.diplome',
      33:'apprenti.nationalite',34:'apprenti.regimeSocial',38:'apprenti.responsableLegal.adresse.adresse2',
      39:'apprenti.responsableLegal.adresse.codePostal',40:'apprenti.responsableLegal.adresse.commune',41:'apprenti.responsableLegal.courriel',
      42:'maitre1.nom',43:'maitre1.prenom',44:'maitre1.courriel',45:'maitre1.emploiOccupe',46:'maitre2.nom',47:'maitre2.prenom',
      48:'maitre2.courriel',49:'maitre2.emploiOccupe',50:'maitre1.intituleDiplomeObtenu',51:'maitre2.intituleDiplomeObtenu',
      52:'maitre1.niveauDiplomeObtenu',53:'maitre2.niveauDiplomeObtenu',54:'contrat.modeContractuel',55:'contrat.numeroContratPrecedent',
      68:'contrat.dureeTravailHebdoHeures',69:'contrat.dureeTravailHebdoMinutes',70:'contrat.typeDerogation',71:'contrat.typeContratApp',
      73:'organismeFormation.uaiCfa',74:'organismeFormation.siret',75:'formation.codeDiplome',76:'formation.rncp',77:'formation.typeDiplome',
      78:'organismeFormation.adresse.commune',81:'organismeFormation.adresse.adresse2',82:'organismeFormation.adresse.codePostal',
      83:'organismeFormationLieuFormationPrincipal.siret',84:'organismeFormationLieuFormationPrincipal.uaiCfa',
      85:'organismeFormationLieuFormationPrincipal.adresse.commune',88:'organismeFormationLieuFormationPrincipal.adresse.adresse2',
      89:'organismeFormationLieuFormationPrincipal.adresse.codePostal',90:'contrat.lieuSignatureContrat',99:'organismeFormation.denomination',
      100:'formation.intituleQualification',101:'organismeFormationLieuFormationPrincipal.denomination',102:'formation.nombreHeuresEnDistanciel'}
    for n,path in mapping.items():field(n,at(data,'cerfa.'+path))
    if not at(data,'cerfa.employeur.codeIdccConventionAppliquee'):field(6,at(data,'cerfa.employeur.codeIdcc'))
    for prefix,num,street in [('employeur',14,13),('apprenti',19,20),('apprenti.responsableLegal',37,36),('organismeFormation',79,80),('organismeFormationLieuFormationPrincipal',86,87)]:
        address=at(data,'cerfa.'+prefix+'.adresse.adresse1','')
        m=re.match(r'^(\d+\s*(?:bis|ter)?)\s+(.+)$',address,re.I)
        field(num,m[1] if m else '');field(street,m[2] if m else address)
    legal=at(data,'cerfa.apprenti.responsableLegal',{})
    field(35,' '.join(filter(None,(legal.get('nom'),legal.get('prenom')))))
    for n,path in [(7,'apprenti.dateNaissance'),(4,'maitre1.dateNaissance'),(1,'maitre2.dateNaissance'),
                   (16,'contrat.dateConclusion'),(19,'contrat.dateDebutContrat'),(22,'contrat.dateFormationPratiqueEmployeur'),
                   (10,'contrat.dateFinContrat'),(25,'formation.dateDebutFormation'),(28,'formation.dateFinFormation')]:dt(n,'cerfa.'+path)
    field(74,at(data,'cerfa.employeur.caisseComplementaire'),'Zone de texte 21')
    field(80,at(data,'cerfa.formation.dureeFormation'),'Zone de texte 21')
    def money(path,whole,decimal,wp='Zone de texte 21'):
        v=at(data,path)
        if isinstance(v,(int,float)):
            a,b=f'{v:.2f}'.split('.');field(whole,a,wp);field(decimal,b,'Zone de texte 21')
    money('cerfa.contrat.salaireEmbauche',72,73,'Zone de texte 8')
    money('cerfa.contrat.avantageNourriture',75,76);money('cerfa.contrat.avantageLogement',77,78)
    if at(data,'cerfa.contrat.autreAvantageEnNature') is not None:field(79,'Oui' if at(data,'cerfa.contrat.autreAvantageEnNature') else 'Non','Zone de texte 21')
    employer=at(data,'cerfa.employeur.typeEmployeur')
    if employer:check('1' if employer<20 else '2',True)
    check('2_2',at(data,'cerfa.employeur.regimeSpecifique'))
    sex=at(data,'cerfa.apprenti.sexe');check('3',sex=='M');check('4',sex=='F')
    for yes,no,path in [('5','5_2','apprenti.inscriptionSportifDeHautNiveau'),('5_3','5_4','apprenti.handicap'),
       ('5_5','5_6','apprenti.droitsRqthEquivalenceJeune'),('5_7','5_8','apprenti.droitsRqthExtensionBOE'),
       ('5_9','5_10','apprenti.projetCreationRepriseEntreprise'),('5_13','5_14','contrat.travailRisque'),
       ('5_11','5_12','organismeFormation.formationInterne')]:boolean(yes,no,'cerfa.'+path)
    check('6',at(data,'cerfa.employeur.attestationEligibilite'));check('8',at(data,'cerfa.employeur.attestationPieces'))
    check('7',at(data,'cerfa.organismeFormation.lieuFormationIdentique'))
    slots={'1.1':(81,95),'1.2':(87,97),'2.1':(37,56),'2.2':(43,58),'3.1':(49,60),'3.2':(55,62),'4.1':(61,64),'4.2':(67,66)}
    for p in at(data,'cerfa.contrat.remunerationsAnnuelles',[]):
        if p.get('ordre') not in slots:continue
        start,n=slots[p['ordre']]
        for offset,key in [(0,'dateDebut'),(3,'dateFin')]:
            value=p.get(key,'')[:10]
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
                y,m,d=value.split('-')
                for index,v in zip(range(start+offset,start+offset+3),(d,m,y)):field(index,v,'Zone de texte 21')
        field(n,p.get('taux'));field(n+1,p.get('typeSalaire'))
    return values


def cerfa_pdf(data):
    reader=PdfReader(TEMPLATE);writer=PdfWriter();writer.clone_document_from_reader(reader)
    values=cerfa_values(data)
    assert set(values)<=set(reader.get_fields()),'CERFA template changed'
    writer.update_page_form_field_values(None,values,auto_regenerate=False)
    output=BytesIO();writer.write(output)
    check=PdfReader(BytesIO(output.getvalue())).get_fields()
    if any(str(check[k].get('/V',''))!=str(v) for k,v in values.items()):raise ValueError('Le CERFA généré n’a pas pu être vérifié.')
    return output.getvalue()


def agreement_pdf(data,details,reference):
    out=BytesIO();styles=getSampleStyleSheet()
    regular,bold=_fonts()
    styles.add(ParagraphStyle('IA',fontName=regular,fontSize=9.5,leading=14,textColor=colors.HexColor('#26334b'),spaceAfter=8))
    styles.add(ParagraphStyle('IAH',parent=styles['IA'],fontName=bold,fontSize=13,leading=17,spaceBefore=14,spaceAfter=9,keepWithNext=True))
    styles.add(ParagraphStyle('IAT',parent=styles['IA'],fontName=bold,fontSize=25,leading=29,spaceAfter=12))
    def p(value,style='IA'):return Paragraph(escape(str(value or 'À compléter')).replace('\n','<br/>'),styles[style])
    def address(prefix):
        a=at(data,prefix+'.adresse',{})
        return ' · '.join(str(x) for x in (a.get('adresse1'),a.get('adresse2'),a.get('codePostal'),a.get('commune')) if x)
    def fmt(v):
        v=str(v or '')[:10]
        return '/'.join(reversed(v.split('-'))) if re.fullmatch(r'\d{4}-\d{2}-\d{2}',v) else 'À compléter'
    def euro(v):return f'{float(v):,.2f} €'.replace(',',' ').replace('.',',') if isinstance(v,(int,float)) else 'À compléter'
    c=at(data,'cerfa',{});f=c.get('formation',{});a=c.get('apprenti',{});e=c.get('employeur',{});org=c.get('organismeFormation',{});co=at(data,'convention',{})
    story=[p('INTÉGRALE ACADEMY'),p('Convention de formation\npar apprentissage','IAT'),p(f'Dossier #{reference} · Document à relire et à signer'),Spacer(1,4*mm)]
    sections=[
      ('01 · Les parties',f"Le CFA : {org.get('denomination','À compléter')}\n{address('cerfa.organismeFormation')}\nSIRET : {org.get('siret','À compléter')} · UAI : {org.get('uaiCfa','À compléter')}\nDéclaration d’activité : {details.get('nda','À compléter')}\nReprésenté par : {details.get('cfa_signer','À compléter')}\n\nL’employeur : {e.get('denomination','À compléter')}\n{address('cerfa.employeur')}\nSIRET : {e.get('siret','À compléter')} · IDCC : {e.get('codeIdcc','À compléter')}\nReprésenté par : {details.get('employer_signer','À compléter')}\nContact : {e.get('courriel','À compléter')} · {e.get('telephone','À compléter')}"),
      ('02 · Bénéficiaire et formation',f"Apprenti : {a.get('prenom','')} {a.get('nom','')} · Né(e) le {fmt(a.get('dateNaissance'))}\nFormation : {f.get('intituleQualification','À compléter')}\nCode RNCP : {f.get('rncp','À compléter')} · Code diplôme : {f.get('codeDiplome','À compléter')}\nDu {fmt(f.get('dateDebutFormation'))} au {fmt(f.get('dateFinFormation'))}\nDurée : {f.get('dureeFormation','À compléter')} heures, dont {f.get('nombreHeuresEnDistanciel','À compléter')} heures à distance.\nContrat : du {fmt(at(data,'cerfa.contrat.dateDebutContrat'))} au {fmt(at(data,'cerfa.contrat.dateFinContrat'))}.\nLieu de formation : {address('cerfa.organismeFormation') if org.get('lieuFormationIdentique') else address('cerfa.organismeFormationLieuFormationPrincipal')}"),
      ('03 · Objectifs et programme',details.get('objectives')),
      ('04 · Organisation et moyens pédagogiques',details.get('organization')),
      ('05 · Suivi, évaluation et sanction',details.get('assessment')),
      ('06 · Conditions financières',f"Coût pédagogique total : {euro(at(data,'convention.couts.coutTotalPedagogieCFA'))}\nRégime de TVA : {details.get('vat','À compléter')}\nFrais de premier équipement : {euro(at(data,'convention.couts.montantPremierEquipement'))}\nNombre de repas prévus : {at(data,'convention.couts.nombreRepasTotaux','À compléter')} · Nuitées : {at(data,'convention.couts.nombreHebergementTotaux','À compléter')}\n\n{details.get('payment_terms','À compléter')}\nLe financement par l’OPCO reste soumis à sa décision de prise en charge. Aucune somme ne peut être demandée à l’apprenti au titre du coût de sa formation."),
      ('07 · Engagements et interruption',details.get('terms')),
      ('08 · Mandat et signatures',('L’employeur mandate le CFA pour les formalités de dépôt du présent dossier auprès de l’OPCO.' if co.get('mandatEmployeur') else 'Mandat de dépôt : non accordé ou à compléter.')+'\nDate : '+fmt(co.get('dateSignature'))+'\nLes parties attestent avoir pris connaissance de la présente convention et de ses annexes.')]
    for title,text in sections:story.extend([p(title,'IAH'),p(text)])
    signatures=Table([[p('Pour le CFA\nNom, qualité et signature'),p('Pour l’employeur\nNom, qualité et signature')],[Spacer(1,22*mm),Spacer(1,22*mm)]],colWidths=[85*mm,85*mm])
    signatures.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.6,colors.HexColor('#d7deeb')),('INNERGRID',(0,0),(-1,-1),.4,colors.HexColor('#d7deeb')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10)]))
    story.extend([Spacer(1,5*mm),KeepTogether(signatures)])
    def footer(canvas,doc):
        canvas.saveState();canvas.setFillColor(colors.HexColor('#596881'));canvas.setFont(regular,8)
        canvas.drawString(20*mm,12*mm,f'Intégrale Academy · Convention #{reference}')
        canvas.drawRightString(190*mm,12*mm,f'{doc.page}');canvas.restoreState()
    SimpleDocTemplate(out,pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=18*mm,bottomMargin=23*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
