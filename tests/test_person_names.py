"""The web, server and document renderers share Prénom NOM without editing data."""
from pathlib import Path
import json
import subprocess

from jinja2 import Environment, FileSystemLoader, select_autoescape
import pytest

from person_names import person_name, person_initials


CASES = [
    ('  de  la tour ', ' éLODIE-mARIE ', 'Élodie-Marie DE LA TOUR', 'ÉD'),
    ('o’neill', "d'ARCY", "D'Arcy O’NEILL", 'DO'),
    ('prati', 'antonio', 'Antonio PRATI', 'AP'),
    ('', 'clément', 'Clément', 'C'),
    ('vaillant', None, 'VAILLANT', 'V'),
    (None, None, '', ''),
]


@pytest.mark.parametrize('last,first,expected,initials', CASES)
def test_python_and_jinja_use_first_name_before_uppercase_surname(last,first,expected,initials):
    assert person_name(last,first)==expected
    assert person_initials(last,first)==initials
    templates=Path(__file__).resolve().parents[1]/'templates'
    macros=Environment(loader=FileSystemLoader(templates),autoescape=select_autoescape(['html'])).get_template('person_names.html').module
    # Compare rendered text, including apostrophes escaped in HTML attributes.
    from html import unescape
    assert unescape(str(macros.person_name(last,first)))==expected
    assert str(macros.person_initials(last,first))==initials


def test_browser_names_match_server_names():
    source=Path(__file__).resolve().parents[1]/'static/js/person-names.js'
    script="global.window={};require(process.argv[1]);const cases=JSON.parse(process.argv[2]);process.stdout.write(JSON.stringify(cases.map(([last,first])=>[window.AcademyNames.fullName(last,first),window.AcademyNames.initials(last,first)])));"
    result=subprocess.run(['node','-e',script,str(source),json.dumps(CASES)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==[[expected,initials] for _,_,expected,initials in CASES]
