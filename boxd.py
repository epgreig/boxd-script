#!/usr/bin/env python3
"""Local, standard-library-only incremental Letterboxd CSV preparation."""
import argparse
import csv
import difflib
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import unicodedata
import uuid
import zipfile
from datetime import date
from xml.etree import ElementTree as ET
from decisions import read_policy, make_row, register

ROOT = Path(__file__).resolve().parent
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
FIELDS = ['Title', 'Year', 'Rating', 'Review', 'Liked', 'WatchedDate']

class Problem(Exception):
    pass

def normalized(text):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower())

def identity(title, year):
    return normalized(title) + ':' + str(year)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def parse_docx(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    entries, active, tier = [], None, ''
    for p in root.findall('.//w:body/w:p', NS):
        text = ''.join(n.text or '' if n.tag == '{'+NS['w']+'}t' else '\n' if n.tag == '{'+NS['w']+'}br' else '\t'
                       for n in p.iter() if n.tag in {'{'+NS['w']+'}t', '{'+NS['w']+'}br', '{'+NS['w']+'}tab'}).strip()
        if not text:
            continue
        if re.match(r'^Tier\s+[1-4]', text):
            tier, active = text.split(':')[0], None
            continue
        m = re.fullmatch(r'(.+?)\s*\((\d{4})\)\s*[-–—]\s*(\d(?:\.\d)?)\s+stars?(.*)', text, re.I)
        if m:
            title, year, old, suffix = m.groups()
            active = dict(title=title.strip(), year=year, old=float(old), tier=tier,
                          suffix=suffix.strip(), paragraphs=[], bullets=[], metadata={})
            active['key'] = identity(active['title'], year)
            entries.append(active)
        elif re.search(r'\s[-–—]\s*(?:\d(?:\.\d)?\s+stars?|DNF)\b', text, re.I) and len(text) < 180:
            raise Problem('Unrecognized entry heading (use Title (YYYY) - N stars): '+text)
        elif active is not None:
            marker = re.fullmatch(r'\[\s*(Letterboxd rating|Watched|New film|Liked)\s*:\s*(.*?)\s*\]', text, re.I)
            if marker:
                k, v = marker.groups()
                if k.lower() in active['metadata']:
                    raise Problem('Duplicate metadata: '+text)
                active['metadata'][k.lower()] = v
            else:
                if text.startswith('[') and re.search(r'watched|letterboxd|new film|redact|liked', text, re.I) and not re.fullmatch(r'\[redact review for upload\]', text, re.I):
                    raise Problem('Unrecognized control marker: '+text)
                active['paragraphs'].append(text)
                active['bullets'].append(p.find('w:pPr/w:numPr', NS) is not None)
    if root.findall('.//w:tbl', NS):
        raise Problem('Document contains tables. Put movie entries in ordinary paragraphs to avoid silently missing entries.')
    keys = [e['key'] for e in entries]
    if not keys or len(keys) != len(set(keys)):
        raise Problem('Document is empty or contains duplicate title/year entries. Rewatches must be handled manually.')
    return entries

def review(entry):
    if any(re.fullmatch(r'\[redact review for upload\]', t, re.I) for t in entry['paragraphs']):
        return ''
    texts = ([entry['suffix'].strip('()')] if entry['suffix'] else []) + entry['paragraphs']
    flags = ([False] if entry['suffix'] else []) + entry['bullets']
    output = []
    for text, bullet in zip(texts, flags):
        label = re.match(r'^(?:(?:On )?[Rr]ewatch(?:ing|ed)?(?: in \d{4})?|Second viewing):', text)
        if label:
            end = label.end()
            value = '<b>'+html.escape(text[:end], quote=True)+'</b>'+html.escape(text[end:], quote=True)
            if end == len(text):
                bullet = False
        else:
            value = html.escape(text, quote=True)
        output.append(('• ' if bullet else '')+value)
    return '<br><br>'.join(output)

def source_signature(e):
    return {'old': e['old'], 'tier': e['tier']}

def metadata(e, required=False):
    m, values = e['metadata'], {}
    for key in ['letterboxd rating', 'watched']:
        if required and key not in m:
            raise Problem('Missing ['+key.title()+': ...]')
    if required and m.get('new film', '').lower() != 'yes':
        raise Problem('Add [New film: yes] only after checking this is not a renamed existing film or rewatch')
    if 'letterboxd rating' in m:
        try:
            n = float(m['letterboxd rating'])
        except ValueError:
            raise Problem('Invalid Letterboxd rating')
        if not .5 <= n <= 5 or n*2 != int(n*2):
            raise Problem('Letterboxd rating must be 0.5–5 in half-star steps')
        values['Rating'] = f'{n:g}'
    if 'watched' in m:
        value = m['watched']
        if value.lower() == 'unknown':
            value = ''
        elif re.fullmatch(r'\d{4}', value):
            value += '-01-01'
        try:
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise Problem('Watched must be YYYY, YYYY-MM-DD, or unknown')
        if not value and m['watched'].lower() != 'unknown':
            raise Problem('Use Watched: unknown to intentionally leave the date blank')
        values['WatchedDate'] = value
    if 'liked' in m:
        if m['liked'].lower() not in ['yes', 'no']:
            raise Problem('Liked must be yes or no')
        values['Liked'] = str(m['liked'].lower() == 'yes').lower()
    return values

class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.private = self.home/'private'
        self.path = self.private/'import-history.json'
        self.lock = self.private/'.lock'

    def __enter__(self):
        self.private.mkdir(parents=True, exist_ok=True)
        try:
            self.lock.mkdir()
        except FileExistsError:
            raise Problem('Another run may be active. If no run is active, remove private/.lock and retry.')
        return self

    def __exit__(self, *args):
        self.lock.rmdir()

    def load(self):
        legacy = self.private/'state.json'
        if not self.path.exists() and legacy.exists():
            # Preserve established upload history; never regenerate it from current decisions.
            try:
                prior = json.loads(legacy.read_text())
                if prior['version'] != 1 or not isinstance(prior['imported'], dict):
                    raise ValueError()
            except (ValueError, KeyError):
                raise Problem('Legacy state is damaged; refusing migration.')
            self.save(prior)
            legacy.rename(self.private/'legacy-state.json')
        try:
            s = json.loads(self.path.read_text())
            if s['version'] != 1 or not isinstance(s['imported'], dict):
                raise ValueError()
            return s
        except FileNotFoundError:
            raise Problem('Run init first.')
        except (ValueError, KeyError):
            raise Problem('Import history is damaged. Stop importing and inspect the backups; do not reset the baseline.')

    def save(self, state):
        data = json.dumps(state, ensure_ascii=False, indent=2).encode()
        if self.path.exists():
            backups = self.private/'backups'
            backups.mkdir(exist_ok=True)
            shutil.copy2(self.path, backups/(uuid.uuid4().hex+'.json'))
        temp = self.path.with_suffix('.tmp')
        with temp.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(self.path)

    def init(self):
        if self.path.exists() or (self.private/'state.json').exists():
            raise Problem('Already initialized. Refusing to erase import history.')
        source = parse_docx(self.private/'source-baseline.docx')
        rules, policy = read_policy(self.home)
        rows = [make_row(e,rules,policy,review) for e in source]
        imported, aliases = {}, {}
        for e, row in zip(source, rows):
            key = identity(row['Title'], row['Year'])
            if key in imported:
                raise Problem('Duplicate baseline film')
            imported[key] = {'row':row, 'source':source_signature(e)}
            aliases[e['key']] = key
        self.save(dict(version=1, imported=imported, aliases=aliases, batches={}, pending=None))
        return f'Initialized {len(imported)} already-imported films.'

    def prepare(self, document):
        s = self.load()
        rules, policy = read_policy(self.home)
        if s['pending']:
            raise Problem('Pending batch '+s['pending']+'. Confirm successful imports or discard the unimported remainder before preparing another.')
        entries = parse_docx(document)
        new, changes, blocked, seen = [], [], [], set()
        for e in entries:
            key = s['aliases'].get(e['key'], e['key'])
            if key in seen:
                raise Problem('Two source entries resolve to the same film: '+e['title'])
            seen.add(key)
            if key in s['imported']:
                old = s['imported'][key]
                differences = []
                if review(e) != old['row']['Review']:
                    differences.append('clear existing review' if not review(e) else 'edit existing review')
                if source_signature(e) != old['source']:
                    differences.append('source rating/tier changed; choose final rating manually')
                try:
                    explicit = {k:v for k,v in make_row(e,rules,policy,review).items() if k!='Review'} if e['key'] in rules['historical_order'] else {}
                    explicit.update(metadata(e))
                    differences.extend('edit '+k for k,v in explicit.items() if old['row'].get(k) != v)
                except (Problem, ValueError) as error:
                    blocked.append(e['title']+': '+str(error))
                if differences:
                    changes.append((e, differences, review(e)))
            else:
                try:
                    values = metadata(e, required=True)
                    # Close matches require explicit alias resolution rather than automatic new-film creation.
                    near = [k for k,v in s['imported'].items() if normalized(v['row']['Title']) == normalized(e['title']) or
                            (str(v['row']['Year']) == e['year'] and difflib.SequenceMatcher(None, normalized(v['row']['Title']), normalized(e['title'])).ratio() > .86)]
                    if near and e['metadata'].get('new film', '').lower() == 'yes':
                        raise Problem('Possible existing film: '+', '.join(near)+'. Use alias if it is the same film; handle distinct same-title films manually.')
                    row = dict(Title=e['title'], Year=e['year'], Review=review(e), Liked='false', **{k:v for k,v in values.items() if k!='Liked'})
                    row['Liked'] = values.get('Liked', 'false')
                    new.append(dict(key=key, row=row, source=source_signature(e), source_key=e['key']))
                except Problem as error:
                    blocked.append(e['title']+' ('+e['year']+'): '+str(error))
        export_dir = self.home/'exports'
        export_dir.mkdir(exist_ok=True)
        report = ['# Changes to existing films — edit manually on Letterboxd', '',
                  'These entries are never included in the new-film CSV. Redactions require clearing the already-published text.', '']
        for e, differences, text in changes:
            report += ['## '+e['title']+' ('+e['year']+')', ', '.join(differences), '', text or '(Clear the review text.)', '']
        report += ['## Needs attention', ''] + (blocked or ['None.'])
        report += ['', '## Missing from document', 'Deletion from the document never deletes an imported film.', '']
        report += [v['row']['Title'] for k,v in s['imported'].items() if k not in seen]
        report_path = export_dir/('report-'+uuid.uuid4().hex[:12]+'.md')
        report_path.write_text('\n'.join(report), encoding='utf-8')
        if blocked:
            return f'No CSV created: {len(blocked)} entries need attention. Report: {report_path}'
        if not new:
            return f'No new films. {len(changes)} existing entries need manual edits. Report: {report_path}'
        batch_id = uuid.uuid4().hex[:12]
        batch_dir = export_dir/batch_id
        batch_dir.mkdir()
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(e['row'] for e in new)
        data = stream.getvalue().encode('utf-8')
        if len(data) >= 1_000_000:
            raise Problem('Batch exceeds Letterboxd 1 MB limit. Use a smaller source document for the new entries.')
        path = batch_dir/'new-films.csv'
        path.write_bytes(data)
        manifest = {'id':batch_id, 'items':new, 'confirmed':[], 'csv_hash':digest(data), 'closed':False}
        (batch_dir/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        s['batches'][batch_id] = manifest
        s['pending'] = batch_id
        self.save(s)
        return f'Batch {batch_id}: {len(new)} new films. Import once: {path}\nThen run confirm {batch_id} --all --yes (only after successful import).\nReport: {report_path}'

    def confirm(self, batch_id, only=None, all_rows=False):
        s = self.load()
        if batch_id not in s['batches']:
            raise Problem('Unknown batch')
        b = s['batches'][batch_id]
        if b['closed']:
            raise Problem('Batch is closed; no further confirmation accepted.')
        path = self.home/'exports'/batch_id/'new-films.csv'
        if digest(path.read_bytes()) != b['csv_hash']:
            raise Problem('CSV changed after preparation. Refusing confirmation of an altered batch.')
        try:
            selected = set(range(1,len(b['items'])+1)) if all_rows else {int(n) for n in only.split(',')}
        except (ValueError, AttributeError):
            raise Problem('Use --all or --only 1,3,5 (film rows, excluding header).')
        if not selected or min(selected)<1 or max(selected)>len(b['items']):
            raise Problem('Invalid row numbers')
        for n in sorted(selected):
            e = b['items'][n-1]
            if n in b['confirmed']:
                continue
            if e['key'] in s['imported']:
                raise Problem('Film already recorded as imported; refusing inconsistent state.')
            s['imported'][e['key']] = {'row':e['row'], 'source':e['source']}
            s['aliases'][e['source_key']] = e['key']
            b['confirmed'].append(n)
        if len(b['confirmed']) == len(b['items']):
            b['closed'], s['pending'] = True, None
        self.save(s)
        return f'Recorded {len(b["confirmed"])}/{len(b["items"])} successful imports. Never upload that full batch again.'

    def discard(self, batch_id):
        s = self.load()
        if s['pending'] != batch_id:
            raise Problem('Not the pending batch')
        s['batches'][batch_id]['closed'] = True
        s['pending'] = None
        self.save(s)
        return 'Unconfirmed remainder discarded. Confirmed films remain recorded. Do not upload the discarded CSV.'

    def alias(self, source, target):
        s = self.load()
        if s['pending']:
            raise Problem('Resolve pending batch first.')
        if target not in s['imported'] or source in s['imported'] or (source in s['aliases'] and s['aliases'][source] != target):
            raise Problem('Unknown target or conflicting source identity')
        s['aliases'][source] = target
        self.save(s)
        return 'Alias saved. This source identity will never be exported as a new film.'

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('status')
    sub.add_parser('list')
    dec = sub.add_parser('decisions'); dec.add_argument('document', nargs='?', type=Path)
    audit = sub.add_parser('audit'); audit.add_argument('document', nargs='?', type=Path)
    prep = sub.add_parser('prepare'); prep.add_argument('document', type=Path)
    conf = sub.add_parser('confirm'); conf.add_argument('batch')
    group = conf.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true'); group.add_argument('--only')
    conf.add_argument('--yes', action='store_true', required=True, help='I verified these rows imported successfully')
    disc = sub.add_parser('discard'); disc.add_argument('batch'); disc.add_argument('--remaining-not-imported', action='store_true', required=True)
    alias = sub.add_parser('alias'); alias.add_argument('source_key'); alias.add_argument('existing_key')
    args = p.parse_args(argv)
    try:
        with Store(args.home) as store:
            if args.command == 'init': result = store.init()
            elif args.command == 'prepare': result = store.prepare(args.document)
            elif args.command == 'confirm': result = store.confirm(args.batch, args.only, args.all)
            elif args.command == 'discard': result = store.discard(args.batch)
            elif args.command == 'alias': result = store.alias(args.source_key, args.existing_key)
            elif args.command in ['decisions','audit']:
                rules, policy = read_policy(args.home)
                document = args.document or store.private/'source-baseline.docx'
                entries = parse_docx(document)
                dest = store.private/'decision-register.md'
                dest.write_text(register(entries,rules,policy,review),encoding='utf-8')
                result = 'Decision register: '+str(dest)
                if args.command == 'audit':
                    rows = [make_row(e,rules,policy,review) for e in entries]
                    output = store.private/'audit-reconstructed.csv'
                    with output.open('w',encoding='utf-8',newline='') as f:
                        writer = csv.DictWriter(f,fieldnames=FIELDS)
                        writer.writeheader(); writer.writerows(rows)
                    result += '\nAudit reconstruction (NOT an incremental upload): '+str(output)
            else:
                s = store.load()
                result = '\n'.join(k+'  '+v['row']['Title'] for k,v in s['imported'].items()) if args.command == 'list' else f'{len(s["imported"])} imported films. Pending batch: {s["pending"] or "none"}'
        print(result)
        return 0
    except (Problem, ValueError, KeyError, OSError, zipfile.BadZipFile, ET.ParseError) as error:
        print('Stopped: '+str(error), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
