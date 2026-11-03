from cyclades_pieces import parse_detail


def test_detail_read_only_observation_identified_and_complete():
    record = {"details": {"N° de candidat": "123456789", "N° d’inscription": "001", "Version": "3"}}
    screen = """N° candidat : 0123456789   N° inscription : 001 Version : 3
    Code Etab : 1234567A
    Pièces justificatives conformes : 0 / 2
    A déposer en ligne entre le vendredi 09 octobre 2026 15:00 et le jeudi 12 novembre 2026 23:59 (heure/Paris)
    CINSIG03 : Confirmation d’inscription signée
    Aucun fichier par le candidat
    Aucun fichier par le gestionnaire
    PJ-CONTROLE En attente de contrôle
    IDENT01 : Document justifiant l’identité
    Déposé le 01/11/2026 10:45 (heure/Paris) par le candidat
    Aucun fichier par le gestionnaire
    PJ-CONTROLE Non conforme
    """
    result = parse_detail(screen, record, "1234567A")
    assert result["requested"] == 2 and result["conforming"] == 0
    first, second = result["documents"]
    assert first["review"] == "En attente de contrôle" and first["deposit"] == first["manager"] == "Non déposée"
    assert first["deadline"] == "12/11/2026 à 23h59"
    assert second["deposit"] == "Déposée" and second["review"] == "Non conforme"
    assert parse_detail(screen.replace("0 / 2", "0 / 4"), record, "1234567A") is None
    assert parse_detail(screen.replace("001 Version", "002 Version"), record, "1234567A") is None
    assert parse_detail(screen, record, "0234567A") is None
