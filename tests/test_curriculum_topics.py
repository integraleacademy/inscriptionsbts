from curriculum_topics import curriculum_labels, MOS_U4, MOS_SOURCE


def test_official_mos_u4_labels_handle_typographic_variants_and_ignore_descriptive_prose():
    for name in ['PRÉPARATION ET MISE EN OEUVRE D’UNE PRESTATION DE SÉCURITÉ',
                 "Préparation et mise en œuvre d'une prestation de sécurité"]:
        labels,source,_ = curriculum_labels(name,'MOS',dict(objectives='Réussir le BTS.',pedagogical_content='Un cours intéressant. Des épreuves.'))
        assert labels == list(MOS_U4) and source == MOS_SOURCE
    assert curriculum_labels('Prestation de sécurité','MOS',dict(exam_unit='U4 – Préparation'))[0]==list(MOS_U4)
    assert curriculum_labels('Préparation','MCO',dict(exam_unit='U4'))[0]==[]
    assert curriculum_labels('Management des ressources humaines','MOS',{})[0]==['Organiser le service','Gérer le personnel','Gérer les relations sociales']
    assert curriculum_labels('Client','MOS',dict(exam_unit='E5.2'))[0][0]=='Préparer l’offre commerciale'


def test_explicit_topics_remain_whole_lines_and_are_diploma_specific():
    details=dict(curriculum_topics='• Veille réglementaire : collecter ; analyser.\n- Préparer une prestation\nPréparer une prestation',source_url=MOS_SOURCE)
    assert curriculum_labels('Une matière','MCO',details)[0]==['Veille réglementaire : collecter ; analyser.','Préparer une prestation']
    assert curriculum_labels('Une matière','MCO',dict(objectives='Phrase 1. Phrase 2.',pedagogical_content='Description ; autre description'))[0]==[]
