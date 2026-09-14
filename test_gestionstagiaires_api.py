import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from gestionstagiaires_api import register_gestionstagiaires_api, FIELDS, FILE_FIELDS


class IntegrationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'data.sqlite';self.upload=self.root/'uploads';self.upload.mkdir()
        self.key='synthetic-test-key-'*3
        self.env=patch.dict(os.environ,{'BTS_IMPORT_API_KEY':self.key});self.env.start();self.addCleanup(self.env.stop)
        def connect():
            conn=sqlite3.connect(self.db);conn.row_factory=sqlite3.Row;return conn
        self.connect=connect
        with connect() as conn:
            conn.execute('CREATE TABLE candidats ('+','.join(k+' TEXT' for k in (*FIELDS,*FILE_FIELDS,'token','public_slug'))+')')
            for cid,prenom in [('a','Élodie'),('b','Élise')]:
                conn.execute('INSERT INTO candidats (id,nom,prenom,email,bts,mode,num_secu,token,public_slug,fichiers_ci) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (cid,'EXEMPLE',prenom,cid+'@example.test','MOS','Présentiel','2090683123456','private-token','private-slug',json.dumps(['identity.pdf','../outside.pdf','link.pdf'])))
        (self.upload/'a').mkdir();(self.upload/'a'/'identity.pdf').write_bytes(b'%PDF-fixture')
        (self.root/'outside.pdf').write_bytes(b'private')
        (self.upload/'a'/'link.pdf').symlink_to(self.root/'outside.pdf')
        app=Flask(__name__);app.config['TESTING']=True;register_gestionstagiaires_api(app,connect,self.upload)
        self.client=app.test_client();self.headers={'Authorization':'Bearer '+self.key}

    def test_key_required_and_responses_never_cached(self):
        self.assertEqual(self.client.post('/api/gestionstagiaires/candidats/rechercher',json={'q':'Exemple'}).status_code,401)
        with patch.dict(os.environ,{'BTS_IMPORT_API_KEY':''}):
            self.assertEqual(self.client.get('/api/gestionstagiaires/candidats/a',headers=self.headers).status_code,503)
        r=self.client.get('/api/gestionstagiaires/candidats/a',headers=self.headers)
        self.assertEqual(r.headers['Cache-Control'],'no-store')

    def test_accent_insensitive_search_homonyms_and_minimal_results(self):
        url='/api/gestionstagiaires/candidats/rechercher'
        result=self.client.post(url,json={'q':'exemple'},headers=self.headers).json
        self.assertEqual(len(result['items']),2)
        self.assertNotIn('num_secu',json.dumps(result));self.assertNotIn('token',json.dumps(result))
        result=self.client.post(url,json={'q':'ELODIE exemple'},headers=self.headers).json
        self.assertEqual([p['id'] for p in result['items']],['a'])
        self.assertEqual(self.client.post(url,json={'q':"%' OR 1=1 --"},headers=self.headers).json['items'],[])

    def test_detail_excludes_credentials_and_files_stay_with_selected_candidate(self):
        result=self.client.get('/api/gestionstagiaires/candidats/a',headers=self.headers).json['candidate']
        self.assertEqual(result['num_secu'],'2090683123456')
        self.assertNotIn('token',result);self.assertNotIn('public_slug',result)
        self.assertEqual([d['name'] for d in result['documents']],['identity.pdf'])
        doc_id=result['documents'][0]['id']
        self.assertEqual(self.client.get('/api/gestionstagiaires/candidats/a/documents/'+doc_id,headers=self.headers).data,b'%PDF-fixture')
        self.assertEqual(self.client.get('/api/gestionstagiaires/candidats/b/documents/'+doc_id,headers=self.headers).status_code,404)


if __name__=='__main__':unittest.main()
