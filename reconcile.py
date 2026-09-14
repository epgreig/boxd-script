"""Compare desired document content with a supplied Letterboxd account export.

No network access, ZIP extraction, or changes to successful-import history.
"""
import csv
import hashlib
import html
import io
import json
from pathlib import Path, PurePosixPath
import re
import uuid
import zipfile
from urllib.parse import urlparse


def canonical_review(value):
    # Keep meaningful HTML (including emphasis), but ignore entity spelling and
    # whitespace differences introduced by Letterboxd's HTML serialization.
    value = re.sub(r'<br\s*/?>', '<br>', value, flags=re.I)
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def read_export(path, Problem):
    path = Path(path)
    tables = {}
    hashes = {}
    archive = zipfile.ZipFile(path) if path.is_file() else None
    try:
        # Locate one account root. Never include deleted/orphaned CSVs.
        if archive:
            roots = [str(PurePosixPath(n).parent) for n in archive.namelist()
                     if PurePosixPath(n).name == 'ratings.csv'
                     and not any(p in ('deleted', 'orphaned', '__MACOSX') for p in PurePosixPath(n).parts)]
            if len(roots) != 1:
                raise Problem('Export ZIP must contain exactly one account ratings.csv.')
            root = PurePosixPath(roots[0])
        for name, required in [('ratings.csv', {'Name','Year','Letterboxd URI','Rating'}),
                               ('reviews.csv', {'Name','Year','Letterboxd URI','Rating','Review','Watched Date'}),
                               ('diary.csv', {'Name','Year','Letterboxd URI','Rating','Watched Date'}),
                               ('watched.csv', {'Name','Year','Letterboxd URI'})]:
            try:
                if archive:
                    member = str(root / name)
                    if archive.namelist().count(member) != 1:
                        raise Problem('Missing or duplicated '+name+' in export ZIP.')
                    if archive.getinfo(member).file_size > 50_000_000:
                        raise Problem('Export CSV is unexpectedly large: '+name)
                    data = archive.read(member)
                else:
                    data = (path/name).read_bytes()
            except (KeyError, FileNotFoundError):
                raise Problem('Incomplete Letterboxd export: missing '+name)
            hashes[name] = hashlib.sha256(data).hexdigest()
            reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
            if not required.issubset(reader.fieldnames or []):
                raise Problem('Unexpected columns in '+name)
            tables[name] = list(reader)
    finally:
        if archive:
            archive.close()
    return tables, hashes


def valid_uri(uri):
    parsed = urlparse(uri)
    return parsed.scheme == 'https' and parsed.hostname in ('boxd.it', 'letterboxd.com', 'www.letterboxd.com') and bool(parsed.path.strip('/'))


def prepare(store, document, export, api):
    """Generate separate new-film and review-update CSVs from fresh account data."""
    Problem = api.Problem
    tables, hashes = read_export(export, Problem)
    state = store.load()
    if state['pending']:
        raise Problem('Resolve the legacy pending batch before preparing against a fresh export.')
    entries = api.parse_docx(document)
    rules, policy = api.read_policy(store.home)
    identity_path = store.private/'film-identities.json'
    identities = json.loads(identity_path.read_text()) if identity_path.exists() else {}
    if not isinstance(identities, dict):
        raise Problem('film-identities.json must map source keys to verified film URIs.')
    observations_path = store.private/'export-observations.json'
    observations = json.loads(observations_path.read_text()) if observations_path.exists() else {}
    if not isinstance(observations, dict):
        raise Problem('Export observations are damaged; refusing to forget previously seen films.')
    films = {}
    for table in ('watched.csv', 'ratings.csv'):
        for row in tables[table]:
            key = api.identity(row['Name'], row['Year'])
            if key in films and films[key]['Letterboxd URI'] != row['Letterboxd URI']:
                raise Problem('Ambiguous film identity in export: '+row['Name'])
            films[key] = row
    reviews = {}
    for row in tables['reviews.csv']:
        key = api.identity(row['Name'], row['Year'])
        reviews.setdefault(key, []).append(row)
    diary = {}
    for row in tables['diary.csv']:
        key = api.identity(row['Name'], row['Year'])
        diary.setdefault(key, []).append(row)

    new, updates, manual, blocked, matched, proposed = [], [], [], [], set(), {}
    for entry in entries:
        title = entry['title']+' ('+entry['year']+')'
        key = entry['key']
        try:
            if entry.get('rating_scale') == 5 or key in rules['historical_order']:
                desired = api.make_row(entry, rules, policy, api.review)
                desired.update(api.metadata(entry))
            else:
                desired = dict(Title=entry['title'], Year=entry['year'], Review=api.review(entry), Liked='false')
                desired.update(api.metadata(entry))
            candidates = {api.identity(desired['Title'], desired['Year']), state['aliases'].get(key, key)}
            if key in identities:
                candidates = {k for k,v in films.items() if v['Letterboxd URI'] == identities[key]}
            matches = [k for k in candidates if k in films]
            if len(matches) > 1:
                raise Problem('Multiple possible films; verify identity.')
            if not matches:
                known = key in observations or key in rules['historical_order'] or key in identities or state['aliases'].get(key,key) in state['imported']
                if known:
                    raise Problem('Previously recorded film missing or differently named in export; verify its film URI. Never automatically re-add.')
                near = [v['Name'] for v in films.values() if api.normalized(v['Name']) == api.normalized(entry['title']) or
                        (v['Year'] == entry['year'] and api.difflib.SequenceMatcher(None, api.normalized(v['Name']), api.normalized(entry['title'])).ratio() > .86)]
                if near:
                    raise Problem('Possible existing film: '+', '.join(near)+'; verify identity.')
                desired.update(api.metadata(entry, required=True))
                new.append(desired)
                if desired.get('Liked') == 'true':
                    manual.append(title+': apply heart manually after import.')
                continue
            match = matches[0]
            if match in matched:
                raise Problem('Two document entries match the same exported film.')
            matched.add(match)
            film = films[match]
            link = film['Letterboxd URI']
            if not valid_uri(link):
                raise Problem('Invalid film URI in export.')
            # Proposed mappings are reviewable output, not automatically trusted.
            proposed[key] = link
            observations[key] = link
            rs, ds = reviews.get(match, []), diary.get(match, [])
            current = film.get('Rating', '')
            if 'Rating' in desired and desired['Rating'] != current:
                manual.append(f'{title}: current film rating {current or "unrated"} → {desired["Rating"]}. {link}')
            for row in rs + [d for d in ds if d['Letterboxd URI'] not in {r['Letterboxd URI'] for r in rs}]:
                if 'Rating' in desired and row['Rating'] != desired['Rating']:
                    manual.append(f'{title}: entry rating {row["Rating"] or "unrated"} → {desired["Rating"]}. {row["Letterboxd URI"]}')
            if len(rs) > 1 or len(ds) > 1:
                manual.append(title+': multiple review/diary entries; choose and edit the intended entry manually. '+link)
                continue
            if not rs:
                if desired['Review']:
                    manual.append(title+': review absent (possibly deleted); add/restore manually. '+link)
                if ds and 'WatchedDate' in desired and ds[0]['Watched Date'] != desired['WatchedDate']:
                    manual.append(title+': watched date differs; edit manually. '+link)
                continue
            existing = rs[0]
            if not valid_uri(existing['Letterboxd URI']):
                raise Problem('Invalid existing review URI.')
            original_date = existing['Watched Date']
            if ds and (ds[0]['Letterboxd URI'] != existing['Letterboxd URI'] or ds[0]['Watched Date'] != original_date):
                manual.append(title+': diary/review identity or date conflict; inspect manually. '+link)
                continue
            if 'WatchedDate' in desired and desired['WatchedDate'] != original_date:
                manual.append(f'{title}: watched date {original_date or "unknown"} → {desired["WatchedDate"] or "unknown"}; update manually before review import. '+existing['Letterboxd URI'])
                continue
            if canonical_review(desired['Review']) == canonical_review(existing['Review']):
                continue
            if not desired['Review'] or not original_date:
                manual.append(title+': '+('clear published review' if not desired['Review'] else 'undated review update has not been tested')+'; edit manually. '+existing['Letterboxd URI'])
                continue
            updates.append(dict(LetterboxdURI=existing['Letterboxd URI'], WatchedDate=original_date, Review=desired['Review']))
        except (Problem, ValueError) as error:
            blocked.append(title+': '+str(error))

    output = store.home/'exports'/('sync-'+uuid.uuid4().hex[:12])
    output.mkdir(parents=True)
    report = ['# Document versus Letterboxd export', '',
              'Document: '+str(Path(document).resolve()), 'Account export: '+str(Path(export).resolve()), '',
              'Use a fresh account export after each import or manual edit. Never re-upload a previous batch.', '',
              f'{len(new)} new films; {len(updates)} review updates; {len(blocked)} unresolved entries.', '',
              '## Manual changes', ''] + (manual or ['None.'])
    report += ['', '## Document formatting notes', ''] + ([e['title']+': '+w for e in entries for w in e.get('warnings', [])] or ['None.'])
    report += ['', '## Needs identity or metadata attention', ''] + (blocked or ['None.'])
    report += ['', '## Account films not matched to the document', '']
    report += [v['Name']+' ('+v['Year']+') '+v['Letterboxd URI'] for k,v in films.items() if k not in matched] or ['None.']
    report += ['', '## Upload instructions', '',
               'review-updates.csv: check BOTH Create diary entries based on watched dates and Import reviews. Verify the original entries changed without duplicates.',
               'new-films.csv: review every title/year match in the importer; the file uses title matching for new films. Enable dates and reviews as appropriate.',
               'Ratings on existing entries, date changes, redactions, missing reviews, and undated updates require manual handling.',
               'Headings with / 5 use document ratings and watched years directly. Historical conversion decisions apply only to legacy headings without / 5.']
    payloads = {}
    for name, rows, fields in [('new-films.csv',new,api.FIELDS), ('review-updates.csv',updates,['LetterboxdURI','WatchedDate','Review'])]:
        if rows:
            stream = io.StringIO(newline='')
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader(); writer.writerows(rows)
            data = stream.getvalue().encode('utf-8')
            if len(data) >= 1_000_000:
                blocked.append(name+' exceeds Letterboxd’s 1 MB limit.')
            payloads[name] = data
    if blocked:
        report += ['', 'No CSV files generated. Resolve all needs-attention entries and rerun with a current export.'] + blocked
    else:
        for name, data in payloads.items():
            (output/name).write_bytes(data)
    (output/'report.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    (output/'proposed-film-identities.json').write_text(json.dumps(proposed,ensure_ascii=False,indent=2), encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps(dict(document=str(Path(document).resolve()),
        document_sha256=hashlib.sha256(Path(document).read_bytes()).hexdigest(), export=str(Path(export).resolve()),
        export_hashes=hashes, files={} if blocked else {n:hashlib.sha256(d).hexdigest() for n,d in payloads.items()},
        new_films=len(new), review_updates=len(updates), blocked=blocked), indent=2), encoding='utf-8')
    # Evidence that a film appeared in a supplied account export, not proof that
    # a prepared upload succeeded. Used only to prevent later accidental re-adds.
    temporary = observations_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(observations,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(observations_path)
    return ('No CSV created: resolve needs-attention entries.' if blocked else
            f'Prepared {len(new)} new films and {len(updates)} review updates. Use only the CSV files in this folder.')+'\nReport: '+str(output/'report.md')+'\nAfter importing, download a fresh export for the next comparison. No legacy confirm step is needed.'
