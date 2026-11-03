"""Read the account edition from the already authenticated BTS establishment workspace."""
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

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


def tabbed_activity_url(url, tabs):
    """Carry the tab issued with this activity's verified context selection."""
    from cyclades_portal import CENTRAL, official
    parts = urlsplit(url)
    if not official(url) or parts.hostname != CENTRAL:
        return url
    prefix = next((path for path in tabs if parts.path == path or parts.path.startswith(path+"/")), None)
    params = parse_qsl(parts.query, keep_blank_values=True)
    if not prefix or any(k.casefold() == "ongletid" for k,v in params):
        return url
    suffix = urlencode({"OngletID":tabs[prefix]})
    query = parts.query + ("&" if parts.query else "") + suffix
    return urlunsplit((parts.scheme,parts.netloc,parts.path,query,parts.fragment))


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
    # Use the portal's link event, including delegated menu listeners that
    # are not present as an inline onclick attribute.
    link = leaf.locator("xpath=ancestor-or-self::a[1]")
    action = link if link.count() == 1 else leaf
    if not action.is_visible():
        for parent in leaf.locator("xpath=ancestor::li").all()[:-1]:
            try:
                if action.is_visible():
                    break
                if parent.is_visible():
                    parent.hover(timeout=800)
                    if not action.is_visible():
                        menu = parent.locator(":scope > ul").first
                        toggle = parent.locator(":scope > a, :scope > button").first
                        if menu.count() and not menu.is_visible() and toggle.count() and toggle.is_visible():
                            toggle.click(timeout=1200)
            except Error:
                continue
    if action.is_visible():
        action.click(timeout=3500)
    else:
        action.evaluate("e=>e.click()")
    if (info["href"] and not info["href"].startswith("#") and official(dest)
            and urlsplit(dest).hostname == CENTRAL and "/cycetablissement/portal/" in urlsplit(dest).path):
        wanted_path = urlsplit(dest).path.split("/__")[0].rstrip("/")
        until = time.monotonic() + 2
        while time.monotonic() < until:
            if any(urlsplit(f.url).path.startswith(wanted_path) for w in shell.context.pages for f in w.frames):
                return
            shell.wait_for_timeout(100)
        navigate(shell, dest)


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
            else:
                control.select_option(index=index)
        if control.count():
            heading = control.locator("xpath=ancestor::*[self::h2 or @role='dialog'][1]")
            if heading.count():
                for action in heading.locator("a:visible,button:visible,input[type=image]:visible").all():
                    safe_confirm = action.evaluate("""e => {
                        const icon=e.querySelector('img');
                        const words=[e.title,e.getAttribute('aria-label'),e.textContent,icon?.alt,icon?.title,
                            (icon?.getAttribute('src')||'').split('/').pop()].filter(Boolean).join(' ');
                        return /valider|confirmer|appliquer|validate|confirm|checkmark/i.test(words)
                            && !/génér|regén|annul|supprim|renouv/i.test(words);
                    }""")
                    if safe_confirm and action.is_enabled():
                        action.click(timeout=3000)
                        break
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

    messages = set()
    phase = "menu établissement"
    context_seen = False
    selected_session = False
    attempted, observed = {}, set()
    trace = []
    validated = set()
    render_responses = []
    render_opened = False
    tab_opened = False
    context_codes = set()
    tab_ids = {}
    # Only the two account portlets in this authentication context.
    account_url = re.compile(r"^https://cyclades\.education\.gouv\.fr/cycetablissement/portal/(?:creation_compte_candidat|regenerer_mdp_compte_candidat)(?:/|\?|$)")
    def keep_activity_tab(route):
        req = route.request
        if req.method == "GET" and req.resource_type in ("document","xhr","fetch"):
            target = tabbed_activity_url(req.url,tab_ids)
            if target != req.url:
                route.fallback(url=target)
                return
        route.fallback()

    def observe_route(response):
        if response.request.resource_type in ("document","xhr","fetch") and official(response.url):
            path = route_label(response.url)
            req = response.request
            if req.method == "POST" and "compte_candidat" in path:
                data = dict(parse_qsl(req.post_data or "", keep_blank_values=True))
                tab_id = data.get("OngletID", "")
                if (data.get("cleSelected") in context_codes and tab_id not in ("0","null","undefined")
                        and re.fullmatch(r"[a-zA-Z0-9_-]{1,90}", tab_id)):
                    root = re.match(r"^(/cycetablissement/portal/(?:creation_compte_candidat|regenerer_mdp_compte_candidat))(?:/|$)",urlsplit(req.url).path)
                    if root:
                        tab_ids[root[1]] = tab_id
            if response.ok and "/validerContexte/true" in path:
                validated.add(path.rsplit("/validerContexte",1)[0])
                if (response.request.method == "GET" and response.request.resource_type in ("xhr","fetch")
                        and "text/html" in response.headers.get("content-type","").lower()):
                    render_responses.append(response)
    shell.route(account_url, keep_activity_tab)
    context.on("response", observe_route)
    context.on("page", watch)
    context.on("response", pdf_response)
    watch(shell)
    try:
        if urlsplit(shell.url).hostname != CENTRAL:
            raise CycladesError("Espace établissement inaccessible.")
        phase = "activité comptes élèves"
        if activity == ACTIVITY:
            history = re.compile(r"^(?:suivi|historique|consulter le suivi|suivre) (?:des|les|de mes|mes|de vos) traitements(?: asynchrones| planifiés)?$", re.I)
            routes = set()
            for frame in shell.frames:
                for leaf in frame.get_by_text(history).all():
                    link = leaf.locator("xpath=ancestor-or-self::a[1]")
                    if link.count() == 1:
                        href = link.get_attribute("href") or ""
                        dest = urljoin(frame.url, href)
                        if official(dest) and urlsplit(dest).hostname == CENTRAL:
                            routes.add(route_label(dest))
            if routes:
                trace.append("historique officiel=" + ",".join(sorted(routes)))
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
        while time.monotonic() < deadline and summary is None:
            for frame in frames():
                switch = frame.locator("#selectContexte:visible")
                if switch.count() == 1:
                    context_seen = True
                    for option in switch.locator("option").all():
                        if words(option.inner_text()) == words(session):
                            if value := option.get_attribute("value"):
                                context_codes.add(value)
                # The header switch returns to its blank placeholder after
                # the portal validates the context. Re-submitting it at that
                # point reloads the portlet and discards the active form.
                confirmed = any(path in route_label(frame.url) for path in validated)
                if confirmed:
                    selected_session = True
                elif select_account_context(frame, session, academy, attempted, observed):
                    selected_session = True
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
                known_summary = frame.locator("#suiviCreationCompte:visible")
                if known_summary.count()==1 and SUMMARY.fullmatch(known_summary.get_attribute("value") or ""):
                    button = known_summary
                if not button.count():
                    button = frame.get_by_text(SUMMARY).filter(visible=True)
                if not button.count():
                    button = frame.locator("[title]").filter(visible=True)
                    button = [e for e in button.all() if SUMMARY.fullmatch(e.get_attribute("title") or "")]
                    button = button[0] if button else frame.locator(".__no_cyclades_control")
                enabled_button = next((b for b in button.all() if b.is_enabled()), None)
                if enabled_button is not None:
                    # The activity displays the selected BTS context above its parameters.
                    text = frame.locator("body").inner_text(timeout=1500)
                    target_year = re.search(r"\b20\d{2}\b",session).group()
                    if selected_session or (target_year in words(text).split() and "bts" in words(text).split()
                            and academy in words(text).split()):
                        summary = enabled_button
                        break
                # A creation form itself mentions the word "papillon". Only
                # the file table is an already-open report.
                if (selected_session and frame.get_by_text(re.compile(r"^Liste des documents g[ée]n[ée]r[ée]s$", re.I)).filter(visible=True).count()
                        and frame.locator("tr").filter(has_text=DOCUMENT).filter(visible=True).count()):
                    direct_document = True
                    break
            if direct_document:
                break
            if summary is None:
                active_form = any(f.locator("#suiviCreationCompte").count() for f in frames())
                # Keep the tab identity in the address itself, as well as on
                # its requests. The shell consults location.search on reload.
                tab_view = tabbed_activity_url(shell.url,tab_ids)
                if not tab_opened and tab_view != shell.url and time.monotonic()-start_wait > 1:
                    tab_opened = True
                    navigate(shell,tab_view)
                    continue
                if render_responses and not render_opened and not active_form and time.monotonic()-start_wait > 2:
                    render_opened = True
                    response = render_responses[-1]
                    from lxml import html, etree
                    try:
                        raw_view = response.body()
                    except Error:
                        raw_view = b""
                    try:
                        rendered = html.fromstring(raw_view,base_url=response.url) if len(raw_view) <= MAX_BYTES else None
                    except (etree.ParserError, ValueError):
                        rendered = None
                    if rendered is None:
                        trace.append("vue de validation sans HTML lisible")
                        navigate(shell,tabbed_activity_url(response.url,tab_ids))
                        continue
                    # The selector action is AJAX: its returned portlet view
                    # can differ from the default view that the shell reloads.
                    # Use only a GET view actually returned to this session.
                    targets = []
                    for anchor in rendered.xpath("//a[@href]"):
                        name = " ".join(anchor.itertext()).strip() or anchor.get("title", "")
                        if SUMMARY.fullmatch(name):
                            href = urljoin(response.url,anchor.get("href"))
                            if official(href) and urlsplit(href).hostname == CENTRAL and not anchor.get("href").startswith("#"):
                                targets.append(href)
                    trace.append("liens du compte rendu="+str(len(targets)))
                    navigate(shell,tabbed_activity_url(targets[0] if len(set(targets))==1 else response.url,tab_ids))
                    if len(set(targets))==1:
                        direct_document = True
                        break
                    continue
                if selected_session and "tous_comptes_existants" in messages and time.monotonic() - start_wait > 5:
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
        deadline = time.monotonic() + 20
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
                        download_icon = row.locator("a[download]:visible,[title*='télécharg' i]:visible,img[alt*='charg' i]:visible,img[src*='disquette' i]:visible,img[src*='download' i]:visible")
                        if download_icon.count():
                            leaf = download_icon.first
                            button = leaf.locator("xpath=ancestor-or-self::*[self::a or self::button][1]")
                            control = button if button.count() else leaf
                        else:
                            control = row.locator("a:visible")
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
    except (Error, CycladesError, OSError, ValueError) as exc:
        # Aggregate diagnostics only; no document titles, credentials or IDs.
        shapes = []
        for frame in frames():
            try:
                for label in frame.get_by_text(DOCUMENT).filter(visible=True).all()[:6]:
                    shapes.append(label.evaluate("""e => {
                        const row=e.closest('tr,li');
                        return (row ? row.tagName+':'+[...row.querySelectorAll('a,img,button')].map(x=>x.tagName+
                            ((x.alt+' '+x.title+' '+x.getAttribute('src')).match(/disquette|charg|download|save|pdf/gi)||[]).join('')).join('/') : e.tagName);
                    }"""))
            except Error:
                continue
        controls = []
        for frame in frames():
            try:
                for el in frame.locator("#suiviCreationCompte").all():
                    controls.append(("visible" if el.is_visible() else "caché", "activé" if el.is_enabled() else "désactivé"))
            except Error:
                continue
        why = str(exc) if isinstance(exc,CycladesError) else type(exc).__name__
        logging.getLogger(__name__).warning("CYCLADES %s papillons : %s (%s), onglet reconnu=%s, fichiers=%s, commande=%s, avis=%s",
            academy, phase, why, bool(tab_ids), ",".join(shapes) or "aucun",controls, ",".join(sorted(messages)) if phase != "activité comptes élèves" else "")
        for record in records:
            if slip_key(record) in wanted and record.get("slip_sync") != "not_listed":
                record["slip_sync"] = "unavailable"
        return False
    finally:
        shell.unroute(account_url,keep_activity_tab)
        context.remove_listener("response", observe_route)
        context.remove_listener("response", pdf_response)
        context.remove_listener("page", watch)
        page.remove_listener("download", downloaded)
        for window in context.pages:
            if window not in existing:
                window.close()
        if not page.is_closed() and page.url != original_url:
            from cyclades_portal import open_list_menu
            try:
                # Keep the shell navigation of the current page if available;
                # otherwise go back to the verified menu, not an intermediate
                # context chooser or file-result page.
                for _ in range(4):
                    if (page.url == original_url or page.locator("#ETABLISSEMENT_INSCRIPTION").count()
                        or page.get_by_text(ACTIVITY).count() or page.get_by_text(EXISTING_ACCOUNTS).count()):
                        break
                    if not page.go_back(wait_until="domcontentloaded", timeout=7000):
                        break
                if page.locator("#ETABLISSEMENT_INSCRIPTION").count():
                    open_list_menu(page)
            except Error:
                pass
