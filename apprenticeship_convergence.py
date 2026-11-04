"""Explicit Convergence V2 transfers. No background submissions and no write retries."""
import json
import os
import re
from urllib.parse import urlsplit

import requests

from akto_convergence import recette_headers, HOST, bad_request_reason
from akto_sync import secret
from opco_convergence import Client, ReadError, endpoint
from apprenticeship_data import PROVIDERS, wire_payload


class TransferError(ValueError):
    def __init__(self,message,uncertain=False):
        super().__init__(message)
        self.uncertain=uncertain


def trusted_url(provider,kind,url):
    if provider!='akto':return endpoint(provider,kind,url)
    p=urlsplit(url)
    if p.scheme!='https' or not (p.hostname=='akto.fr' or (p.hostname or '').endswith('.akto.fr')) or p.username or p.password or p.port not in (None,443) or p.query or p.fragment:
        raise ValueError('Saisissez une adresse HTTPS AKTO fournie lors de l’accrochage.')
    return url.rstrip('/')


def connection(app,conn,provider,environment):
    if provider not in PROVIDERS or environment not in ('recette','production'):raise TransferError('Connexion inconnue.')
    if provider=='akto' and environment=='recette':
        row=conn.execute('SELECT credential FROM akto_recette_key WHERE id=1').fetchone()
        if not row or not row[0]:raise TransferError('Enregistrez la clé CFA AKTO de recette dans Paramètres.')
        key=secret(app).decrypt(row[0]).decode()
        try:headers=recette_headers(key)
        except ReadError as e:raise TransferError(str(e)) from None
        return HOST+'/SorApiEchangeCFA',headers
    row=conn.execute('SELECT credential FROM apprenticeship_connections WHERE provider=? AND environment=?',(provider,environment)).fetchone()
    if not row and environment=='production' and provider!='akto':
        row=conn.execute('SELECT credential FROM opco_accounts WHERE provider=?',(provider,)).fetchone()
    if not row or not row[0]:raise TransferError('Configurez les accès Convergence de cet OPCO pour cet environnement.')
    config=json.loads(secret(app).decrypt(row[0]))
    base=trusted_url(provider,'api',config['api']);token_url=trusted_url(provider,'token',config['token'])
    params={'grant_type':'client_credentials'}
    if config.get('scope'):params['scope']=config['scope']
    kwargs={'auth':(config['client_id'],config['client_secret'])} if config.get('auth_mode')=='basic' else {}
    if not kwargs:params.update(client_id=config['client_id'],client_secret=config['client_secret'])
    try:token=Client.json_request('POST',token_url,data=params,**kwargs)
    except ReadError as e:raise TransferError(str(e)) from None
    if not isinstance(token,dict) or not isinstance(token.get('access_token'),str):raise TransferError('Le serveur n’a pas délivré de jeton.')
    return base,{'Authorization':'Bearer '+token['access_token'],'X-API-KEY':config['key'],
        'EDITEUR':'Integrale Academy','LOGICIEL':'Inscriptions BTS','VERSION':'2.0','Accept':'application/json'}


def call(base,headers,method,path,**kwargs):
    writing=method=='POST'
    try:
        with requests.request(method,base+path,headers=headers,timeout=(5,35),allow_redirects=False,stream=True,**kwargs) as response:
            body=bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body)>8_000_000:raise TransferError('Réponse OPCO trop volumineuse. Vérifiez le dossier avant toute nouvelle transmission.',writing)
            try:result=json.loads(body)
            except (ValueError,UnicodeError):raise TransferError('Réponse OPCO illisible. Vérifiez le résultat auprès de l’OPCO.',writing) from None
            if response.status_code not in (200,201) or not isinstance(result,dict) or result.get('status')=='error':
                detail=bad_request_reason(result,headers) if isinstance(result,dict) else ''
                raise TransferError(f'Convergence : HTTP {response.status_code}. '+(detail or 'La demande n’a pas été confirmée.'),writing and (response.status_code>=500 or 200<=response.status_code<400))
            return result
    except requests.RequestException:
        raise TransferError('Le serveur OPCO n’a pas confirmé le résultat. Vérifiez le dossier avant de réessayer.',writing) from None


def submit(base,headers,payload,convention):
    result=call(base,headers,'POST','/v2/dossiers',data={'PostDossierRequestV2':json.dumps(wire_payload(payload),ensure_ascii=False)},
                files={'fichier':('convention-signee.pdf',convention,'application/pdf')})
    if result.get('status')!='success' or not isinstance(result.get('numeroInterne'),str) or not result['numeroInterne']:
        raise TransferError('Accusé de réception incomplet : vérifiez le dossier auprès de l’OPCO.',True)
    return {k:result.get(k,'') for k in ('numeroInterne','numeroExterne')}


def read(base,headers,reference='',external='',deca=''):
    if reference:params={'numeroInterne':reference}
    elif external and deca:params={'numeroExterne':external,'numeroDeca':deca}
    else:raise TransferError('Renseignez le numéro interne OPCO, ou le numéro de dossier OPCO et son DECA.')
    if any(not re.fullmatch(r'[A-Za-z0-9./_-]{1,100}',str(x)) for x in params.values()):raise TransferError('Référence OPCO invalide.')
    result=call(base,headers,'GET','/v2/dossiers',params=params)
    c=result.get('cerfa')
    if not isinstance(c,dict) or not c.get('numeroInterne'):raise TransferError('Le dossier retourné est incomplet.')
    if reference and c['numeroInterne']!=reference:raise TransferError('Le numéro interne retourné ne correspond pas à la demande.')
    if external and c.get('numeroExterne')!=external:raise TransferError('Le numéro de dossier retourné ne correspond pas à la demande.')
    if deca and (not isinstance(c.get('contrat'),dict) or c['contrat'].get('noContrat')!=deca):raise TransferError('Le DECA retourné ne correspond pas à la demande.')
    return result
