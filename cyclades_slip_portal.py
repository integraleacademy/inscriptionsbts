"""Read the account edition from the already authenticated BTS establishment workspace."""
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error

from cyclades_data import ACADEMIES, MAX_BYTES, CycladesError, words
from cyclades_slips import read_slips, slip_key

ACTIVITY = re.compile(r"^G[ée]n[ée]rer\s+les comptes\s+(?:CYCLADES\s+)?(?:de mes|des)\s+[ée]l[èe]ves$", re.I)
EXISTING_ACCOUNTS = re.compile(r"^(?:[Rr][ée]g[ée]n[ée]rer|[Rr][ée]initialiser)\s+le mot de passe (?:d[’'](?:un |une ))?(?:compte |candidat )?(?:(?:d[’'])?un )?(?:[ée]l[èe]ve|candidat)(?: scolaire)?$", re.I)
SUMMARY = re.compile(r"^\s*(?:(?:Afficher|Consulter|Voir|Télécharger)\s+(?:le |les |l[’'])?(?:dernier\s+)?)?(?:dernier\s+)?comptes?[\s-]*rendus?(?:\s+du (?:dernier )?traitement)?[ .]*$", re.I)
DOCUMENT = re.compile(r"papillons?\s*(?:(?:d[’']\s*)?informations?\s*)?(?:de\s*)?connexion(?:\s*cyclades)?", re.I)


def route_label(url):
    # Static portlet names only, never a query, token or candidate identifier.
    return "/".join(x for x in urlsplit(url).path.split("/") if
                    re.fullmatch(r"[A-Za-z][A-Za-z_.-]{0,70}", x))[:140]


def open_accounts_menu(shell, trace, activity, *, alternate=False):
    from cyclades_portal import CENTRAL, navigate, official
    entries = []
    for frame in shell.frames:
        if urlsplit(frame.url).hostname != CENTRAL:
            continue
        for leaf in frame.get_by_text(activity).all():
            info = leaf.evaluate("""e => {
                const a=e.closest('a');
                const groups=[]; for(let n=e;n;n=n.parentElement){
                  if(n.tagName==='LI')groups.push(n.id || n.firstElementChild?.id || '');
                }
                return { href:a?.getAttribute('href')||'', dest:a?.href||'',
                         handler:!!(a?.onclick || e.onclick), groups:groups.filter(x=>/^[A-Za-z_]{2,85}$/.test(x)),
                         nav: !e.closest('button,input[type=submit]') && (!e.closest('form') || !!e.closest('nav,aside,a,li,[role=menuitem]')) };
            }""")
            if not info["nav"]:
                continue
            group = " ".join(info["groups"]).lower()
            entries.append(("inscription" not in group, leaf, info))
    if not entries:
        raise CycladesError("L’activité des comptes est indisponible.")
    entries.sort(key=lambda item:item[0])
    _, leaf, info = entries[-1 if alternate else 0]
    dest = info["dest"]
    trace.append("groupe=" + ",".join(info["groups"]) + " lien=" + (
        route_label(dest) if official(dest) and info["href"] and not info["href"].startswith("#") else
        "action-js" if info["href"].startswith("javascript:") else "ancre") + " handler=" + str(info["handler"]))
    # This is the verified menu's navigation link (never the account form).
    # JS-decorated links must activate their native handler. For a plain link
    # navigate directly to its official destination even in a collapsed menu.
    if (not info["handler"] and info["href"] and not info["href"].startswith("#") and official(dest)
            and urlsplit(dest).hostname == CENTRAL and dest != shell.url and "/cycetablissement/" in urlsplit(dest).path):
        navigate(shell, dest)
        return
    link = leaf.locator("xpath=ancestor-or-self::a[1]")
    action = link if link.count() == 1 else leaf
    action.evaluate("e => e.click()")


CONFIRM_CONTEXT = re.compile(r"^\s*(?:valider|confirmer|continuer|sélectionner|appliquer|ok|accéder|choisir|suivant|ouvrir)(?:\s+(?:(?:la|le|ce|cette|mon|ma)\s+)?(?:session|contexte|choix|sélection)(?: de travail)?)?[!.]?\s*$", re.I)


def select_account_context(frame, session, academy, attempted, observed):
    from cyclades_portal import select_report_context
    control = frame.locator("#selectContexte:visible")
    if control.count() != 1:
        return False
    options = [v.strip() for v in control.locator("option").all_text_contents()]
    year = re.search(r"\b20\d{2}\b", session).group()
    labels = [words(v).split() for v in options]
    observed.update("-".join(t for t in tokens if t in ("bts","paris","nice") or re.fullmatch(r"20\d{2}",t)) or "autre" for tokens in labels)
    exact = [v for v in options if words(v) == words(session)]
    by_year = [v for v,t in zip(options,labels) if year in t and "bts" in t and not (set(t) & ({"paris","nice"} - {academy}))]
    intermediate = [v for v,t in zip(options,labels) if "bts" in t and not any(re.fullmatch(r"20\d{2}",x) for x in t)
                    and not (set(t) & ({"paris","nice"} - {academy}))]
    school = [v for v,t in zip(options,labels) if ACADEMIES[academy][1].lower() in t]
    choices = exact or by_year or intermediate or school
    if len(choices) != 1:
        return False
    choice = choices[0]
    scoped_year = bool(exact or by_year)
    # Playwright reuses the Frame object across navigations. A choice made
    # in the list portlet is not a choice in the account portlet.
    document = (frame, frame.url, frame.evaluate("performance.timeOrigin"), choice)
    scoped_year = bool(exact or by_year)
    selected = control.locator("option:checked").inner_text().strip()
    previous, tries = attempted.get(document, (0, 0))
    if previous and (selected == choice or time.monotonic()-previous < 2 or tries >= 3):
        return False
    attempted[document] = (time.monotonic(), tries+1)
    header_switch = control.evaluate("e => !e.closest('form,.modal,[role=dialog]') && e.parentElement.tagName === 'SPAN'")
    if header_switch:
        if selected != choice:
            index = options.index(choice)
            if index == len(options)-1:
                # The real shell listens to keyboard/mouse activation of the
                # context switch. This also supplies a native user gesture.
                control.press("End")
            if control.count() and control.locator("option:checked").inner_text().strip() != choice:
                control.select_option(index=index)
            if control.count():
                option = control.locator("option").nth(index)
                if option.count():
                    option.dispatch_event("click")
        return scoped_year
    if select_report_context(frame, choice):
        return scoped_year
    if selected != choice:
        control.select_option(index=options.index(choice))
    if control.is_visible():
        confirm = frame.get_by_role("button",name=CONFIRM_CONTEXT).or_(frame.get_by_role("link",name=CONFIRM_CONTEXT)).filter(visible=True)
        if not confirm.count():
            confirm = frame.get_by_text(CONFIRM_CONTEXT).filter(visible=True)
        if confirm.count() == 1 and confirm.is_enabled():
            confirm.click()
    return scoped_year


def read_account_slips(page, academy, session, records, cipher):
    wanted = [r for r in records if slip_key(r)]
    if not wanted:
        return True
    # Cyclades can close the initial account-creation activity once every
    # student has an account. The password-management activity also exposes
    # an existing report. Open only its report, never submit its generator.
    pending = wanted
    outcomes = []
    for activity in (ACTIVITY, EXISTING_ACCOUNTS):
        outcomes.append(read_slip_edition(page, academy, session, pending, cipher, activity))
        pending = [r for r in pending if r.get("slip_sync") != "found"]
        if not pending:
            break
    logging.getLogger(__name__).warning("CYCLADES %s accès automatiques : %d/%d inscriptions avec papillon",
                                        academy, len(wanted)-len(pending), len(wanted))
    return not pending or all(outcomes)


def read_slip_edition(page, academy, session, records, cipher, activity):
    from cyclades_portal import CENTRAL, navigate, official

    wanted = {key for record in records if (key := slip_key(record))}
    if not wanted:
        return True
    context = page.context
    existing = set(context.pages)
    previous = {frame: frame.url for tab in existing if tab != page for frame in tab.frames}
    # Reopening the current CSV/edition URL in a fresh window replays its
    # portlet action. The established shell already contains the active menu.
    shell = page
    original_url = page.url
    downloads, responses = [], []

    def downloaded(item):
        downloads.append(item)

    def watch(window):
        window.on("download", downloaded)

    def pdf_response(response):
        if (official(response.url) and response.ok
                and "application/pdf" in response.headers.get("content-type", "").lower()
                and "attachment" not in response.headers.get("content-disposition", "").lower()
                and previous.get(response.frame) != response.frame.url):
            responses.append(response)

    def frames():
        return [f for window in context.pages for f in window.frames if previous.get(f) != f.url and (
                official(f.url) or (f.url in ("about:blank", "about:srcdoc") and f.parent_frame and official(f.parent_frame.url)))]

    def visible_control(frame, pattern):
        return frame.get_by_role("button", name=pattern).or_(frame.get_by_role("link", name=pattern)).filter(visible=True)

    phase = "menu établissement"
    context_seen = False
    selected_session = False
    attempted, observed = {}, set()
    trace = []
    traffic = set()
    validated = set()
    def observe_route(response):
        if response.request.resource_type in ("document","xhr","fetch") and official(response.url):
            path = route_label(response.url)
            traffic.add(str(response.status)+"-"+path)
            if response.ok and "/validerContexte/true" in path:
                validated.add(path.rsplit("/validerContexte",1)[0])
    context.on("response", observe_route)
    context.on("page", watch)
    context.on("response", pdf_response)
    watch(shell)
    try:
        if urlsplit(shell.url).hostname != CENTRAL:
            raise CycladesError("Espace établissement inaccessible.")
        phase = "activité comptes élèves"
        open_accounts_menu(shell, trace, activity)
        attempted.clear()
        selected_session = False
        logging.getLogger(__name__).warning("CYCLADES %s menu papillons : %s", academy, " | ".join(trace))
        phase = "compte rendu existant"
        start_wait = time.monotonic()
        switched = False
        deadline = start_wait + 32
        summary = None
        direct_document = False
        messages = set()
        while time.monotonic() < deadline and summary is None:
            for frame in frames():
                if frame.locator("#selectContexte:visible").count():
                    context_seen = True
                # The header switch returns to its blank placeholder after
                # the portal validates the context. Re-submitting it at that
                # point reloads the portlet and discards the active form.
                confirmed = any(path in route_label(frame.url) for path in validated)
                if confirmed:
                    selected_session = True
                elif select_account_context(frame, session, academy, attempted, observed):
                    selected_session = True
                    break
                if selected_session and frame.get_by_text(DOCUMENT).filter(visible=True).count():
                    direct_document = True
                    break
                # These are explicit service messages; arbitrary portal text
                # must not be logged or interpreted as a personal credential.
                for key, pattern in (
                    ("tous_comptes_existants", r"tous (?:vos|les) [ée]l[èe]ves (?:possèdent|ont) (?:déjà )?un compte"),
                    ("activité_indisponible", r"(?:activité|édition) n[’']est pas disponible"),
                    ("pas_de_traitement", r"aucun(?:e)? (?:traitement|compte.rendu|édition)"),
                    ("choix_application", r"(?:sélectionnez|choisissez) (?:une? |votre |le )?(?:contexte|session|activité)"),
                    ("erreur_application", r"erreur (?:technique|applicative)|activité (?:non autorisée|inaccessible)"),
                ):
                    if frame.get_by_text(re.compile(pattern,re.I)).filter(visible=True).count():
                        messages.add(key)
                button = visible_control(frame, SUMMARY)
                if not button.count():
                    button = frame.get_by_text(SUMMARY).filter(visible=True)
                if not button.count():
                    button = frame.locator("[title]").filter(visible=True)
                    button = [e for e in button.all() if SUMMARY.fullmatch(e.get_attribute("title") or "")]
                    button = button[0] if button else frame.locator(".__no_cyclades_control")
                if button.count() and button.first.is_enabled():
                    # The activity displays the selected BTS context above its parameters.
                    text = frame.locator("body").inner_text(timeout=1500)
                    target_year = re.search(r"\b20\d{2}\b",session).group()
                    if selected_session or (target_year in words(text).split() and "bts" in words(text).split()
                            and academy in words(text).split()):
                        summary = button.first
                        break
            if direct_document:
                break
            if summary is None:
                if selected_session and "tous_comptes_existants" in messages and time.monotonic() - start_wait > 2:
                    for record in records:
                        record["slip_sync"] = "not_listed"
                    logging.getLogger(__name__).warning("CYCLADES %s : activité initiale close, consultation du compte rendu des accès existants", academy)
                    return True
                if selected_session and not switched and time.monotonic() - start_wait > 12 and not any(
                        "compte_candidat" in urlsplit(f.url).path for f in frames()):
                    # Changing the global session can return the shell to its
                    # start page. Re-enter via the other documented menu.
                    switched = True
                    attempted.clear()
                    open_accounts_menu(shell, trace, activity, alternate=True)
                shell.wait_for_timeout(200)
        if summary is None and not direct_document:
            trace.append("avis=" + (",".join(sorted(messages)) or "aucun"))
            raise CycladesError("Compte rendu indisponible.")
        if summary is not None:
            summary.click()
        phase = "document du compte rendu"
        deadline = time.monotonic() + 12
        clicked = False
        while time.monotonic() < deadline and not (downloads or responses):
            for frame in frames() if not clicked else ():
                labels = frame.get_by_text(DOCUMENT).filter(visible=True)
                for label in labels.all():
                    caption = label.inner_text(timeout=1200)
                    if len(caption) > 180 or re.search(r"2\s*(?:par|/)|deux", caption, re.I):
                        continue
                    # Only the download of this edition, never a generic submit button.
                    control = label.locator("xpath=ancestor-or-self::a[1]")
                    if not control.count():
                        row = label.locator("xpath=ancestor::*[self::tr or self::li][1]")
                        control = row.locator("a:visible,button[title*='charg' i]:visible,img[title*='charg' i]:visible")
                        if not control.count():
                            holder = label.locator("xpath=ancestor::*[.//*[self::a or self::button or self::img]][1]")
                            if holder.count() and holder.get_by_text(DOCUMENT).count() <= 1:
                                control = holder.locator("a:visible,button[title*='charg' i]:visible,img[title*='charg' i]:visible,img[alt*='charg' i]:visible,img[src*='disquette' i]:visible")
                        if not control.count() and label.get_attribute("onclick"):
                            control = label
                    if control.count() == 1:
                        control.click()
                        clicked = True
                        break
                if clicked:
                    break
            shell.wait_for_timeout(200)
        phase = "lecture du PDF"
        raw = b""
        if downloads:
            item = downloads[0]
            if official(item.url.removeprefix("blob:")) and (path := item.path()) and Path(path).stat().st_size <= MAX_BYTES:
                raw = Path(path).read_bytes()
        elif responses:
            response = responses[0]
            size = response.headers.get("content-length", "")
            if not size.isdecimal() or int(size) <= MAX_BYTES:
                raw = response.body()
        if not raw:
            phase = "téléchargement du PDF" if clicked else "lien du PDF"
            raise CycladesError("PDF indisponible.")
        found = read_slips(raw, wanted)
        for record in records:
            if slip_key(record) not in wanted:
                continue
            password = found.get(slip_key(record))
            record["slip_sync"] = "found" if password else "not_listed"
            if password:
                record["sealed_slip"] = cipher.encrypt(password.encode()).decode()
        logging.getLogger(__name__).warning("CYCLADES %s papillons : %d/%d accès rattachés", academy, len(found), len(wanted))
        return True
    except (Error, CycladesError, OSError, ValueError):
        # Keep navigation identifiers only, never page text or candidate data.
        trace.append("lectures="+",".join(sorted(traffic))[:600])
        structure = []
        chooser_controls = []
        doc_routes = []
        buttons = set()
        ids = set()
        controls = set()
        for frame in frames():
            try:
                # Only static control/route identifiers and navigation verbs,
                # no form values or student data. Inspect the chooser's actual
                # siblings and enclosing dialog in addition to the shell.
                route = urlsplit(frame.url).path
                doc_routes.append("/".join(w for w in route.split("/") if
                    re.fullmatch(r"[a-zA-Z_][a-zA-Z_.-]{0,80}",w))[:180])
                buttons.update(frame.locator("input[type=button]:visible,input[type=submit]:visible,button:visible,a[role=button]:visible").evaluate_all("""els => els.map(e=>{
                    const text=[e.innerText,e.title,e.getAttribute('aria-label'),e.matches('input')?e.value:''].join(' ');
                    const words=text.match(/compte|rendu|afficher|génér|édit|valider|contexte|session|télécharg|sélection|choisir|traitement|précédent|confirmation|suivant/gi);
                    return words ? [...new Set(words)].join('+') : '';
                }).filter(Boolean)"""))
                for select in frame.locator("select:visible").all():
                    chooser_controls.append(select.evaluate("""e => {
                      const selected=e.selectedOptions[0], value=selected?.textContent||'';
                      return 'SELECT/'+e.id.replace(/[^A-Za-z_-]/g,'').slice(0,50)+'/'+e.options.length+
                        '/'+(selected?.value?'choisi':'vide')+'/'+(value.match(/bts|paris|nice|20[0-9]{2}|choisir|sélect|contexte|établissement/gi)||[]).join('-');
                    }"""))
                hints = frame.locator("p:visible,h1:visible,h2:visible,h3:visible,.portlet-msg-info:visible,.alert:visible,main:visible").evaluate_all("""els => {
                    const vocab=/aucun|compte|rendu|tous|pas de|disponible|activité|habilitation|droits|autorisé|autorisation|accès|accéder|choisir|choisissez|sélect|contexte|session|traitement|planifi|génér|existe|déjà|désactiv|ouvert|ferm|démarr|chargement|veuillez|papillon|défini|paramétr|édition|erreur|connexion|élève|examen|établissement/gi;
                    return [...new Set(els.filter(e=>!e.closest('nav,header,footer')).map(e=>(e.innerText.match(vocab)||[]).slice(0,30).join(' ')).filter(Boolean))].slice(0,12);
                }""")
                if hints:
                    chooser_controls.append("avis-écran="+" / ".join(hints))
                # Capture only ordered, allowlisted interface words. This
                # includes legacy portlets built entirely from div/span nodes.
                body = frame.locator("body").inner_text(timeout=2000)
                ui_words = set("aucun aucune compte rendu tous pas disponible indisponible activité droits habilité autorisé autorisation accès accéder choisir choisissez sélectionner sélectionnez contexte session traitement générer génération générés existant comptes possèdent déjà ouverts chargement veuillez papillon papillons défini paramètres erreur anomalie problème validation élèves examen établissement examens candidats navigation navigateur fenêtre fenêtres document documents téléchargement édition éditions afficher choix valider service fermé initialisé doit devez enregistrée sélectionner".split())
                rows = [" ".join(w for w in line.casefold().split() if w.strip(".:!,’()") in ui_words)
                        for line in body.splitlines()]
                chooser_controls.append("écran="+" / ".join(r for r in rows if r)[-700:])
                chooser_controls.append("champs="+frame.locator("form,select,input:not([type=hidden]),iframe,object,embed").evaluate_all(
                    """els=>els.slice(-30).map(e=>e.tagName+'#'+(e.id||e.name||'').replace(/[^A-Za-z_-]/g,'').slice(0,48)).join(',')"""))
                chooser_controls.append("cadres="+",".join(route_label(f.url) or urlsplit(f.url).scheme
                    for w in context.pages for f in w.frames)[:480])
                for chooser in frame.locator("#selectContexte:visible").all():
                    chooser_controls.append(chooser.evaluate("""e => {
                        const chain=[]; let n=e;
                        for(let i=0;n && i<5;i++,n=n.parentElement)chain.push(n.tagName+'.'+String(n.className).replace(/[^a-zA-Z_ -]/g,'').slice(0,70));
                        const opt=e.options[Math.max(0,e.options.length-1)];
                        const handlers=n=>['onchange','onclick','oninput','onkeydown','onmousedown'].filter(a=>n && (n[a]||n.hasAttribute(a))).join('+');
                        return 'zone='+chain.join('>')+' événements='+handlers(e)+'/'+handlers(opt)+' option='+
                          (String(opt?.value||'').startsWith('https:') || String(opt?.value||'').startsWith('/')?'url':opt?.value?'code':'vide');
                    }"""))
                    chooser_controls.extend(chooser.evaluate("""e => {
                        const region=e.closest('.modal,dialog,[role=dialog],form') || e.closest('div') || e.parentElement.parentElement;
                        const words=/valider|sélectionner|selectionner|choisir|contexte|session|confirmer|continuer|appliquer|ouvrir|accéder|annuler|fermer|suivant|ok|lancer|activité|afficher|générer/gi;
                        const names=n=>[n.id,n.name,n.title,n.getAttribute('aria-label'),n.matches('input[type=button],input[type=submit]')?n.value:'',n.textContent].filter(Boolean).join(' ');
                        return [e.parentElement.tagName+'>'+region.tagName,...Array.from(region.querySelectorAll('button,input[type=submit],input[type=button],a,[role=button],img[title]'))
                            .filter(n=>n.getClientRects().length).slice(0,20).map(n=>n.tagName+'/'+(n.id||'').replace(/[^a-zA-Z_-]/g,'').slice(0,40)+'/'+[...new Set(names(n).match(words)||[])].join('+'))];
                    }"""))
                # Log structural facts from the menu only. Never values, URLs or PDF text.
                nodes = frame.get_by_text(activity)
                if nodes.count():
                    structure.extend(nodes.evaluate_all("""els => els.slice(0,4).map(e => {
                        const tags=[]; for(let n=e; n && tags.length<5; n=n.parentElement) {
                            tags.push(n.tagName + (n.hasAttribute('onclick')?'*':'') +
                                (n.tagName==='A' && n.getAttribute('href')?'(link)':''));
                        } return tags.join('/');
                    })"""))
                for flag, pattern in (("générer",re.compile("^Générer$",re.I)),
                                      ("choix",re.compile("choisir.*session",re.I)),
                                      ("aucune édition",re.compile("aucun(?:e)? (?:édition|compte.rendu|traitement)",re.I))):
                    if frame.get_by_text(pattern).count():
                        controls.add(flag)
                if frame.locator("#selectContexte:visible").count():
                    controls.add("sélecteur")
                ids.update(frame.locator('[id^="ACTV_"],[id^="ETABLISSEMENT_"]').evaluate_all(
                    "(els) => els.map(e => e.id).filter(s => /^(ACTV|ETABLISSEMENT)_[A-Z_]{1,90}$/.test(s) && /COMPTE|ETABLISSEMENT_|PAPILLON/.test(s))"))
                for name, pattern in (("activité", ACTIVITY), ("compte-rendu", SUMMARY), ("document", DOCUMENT)):
                    if frame.get_by_text(pattern).count():
                        controls.add(name)
            except Error:
                continue
        logging.getLogger(__name__).warning("CYCLADES %s papillons : lecture indisponible (%s), structure %s, contexte %s/%s [%s], commande %s, pages %s, contrôles %s, liens %s, boutons %s, menu %s",
            academy, phase, ",".join(structure) or "—", context_seen, selected_session if phase not in
            ("menu établissement","chargement du menu","activité comptes élèves") else False, ",".join(sorted(observed)), ",".join(chooser_controls), ",".join(doc_routes), ",".join(sorted(controls)) or "—", " | ".join(trace), ",".join(sorted(buttons)) or "—", ",".join(sorted(ids)) or "—")
        for record in records:
            if slip_key(record) in wanted and record.get("slip_sync") != "not_listed":
                record["slip_sync"] = "unavailable"
        return False
    finally:
        context.remove_listener("response", observe_route)
        context.remove_listener("response", pdf_response)
        context.remove_listener("page", watch)
        page.remove_listener("download", downloaded)
        for window in context.pages:
            if window not in existing:
                window.close()
        if not page.is_closed() and page.url != original_url:
            # The next session still uses the existing reports menu.
            from cyclades_portal import open_list_menu
            try:
                if not page.locator("#ETABLISSEMENT_INSCRIPTION").count() or not open_list_menu(page):
                    page.go_back(wait_until="domcontentloaded", timeout=10000)
            except Error:
                pass
