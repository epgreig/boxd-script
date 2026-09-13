import csv
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

spec = importlib.util.spec_from_file_location('boxd', Path(__file__).resolve().parents[1]/'boxd.py')
boxd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boxd)

def document(path, paragraphs):
    xml = '<w:document xmlns:w="'+boxd.NS['w']+'"><w:body>'
    for text in paragraphs:
        xml += '<w:p><w:r><w:t>'+escape(text)+'</w:t></w:r></w:p>'
    xml += '</w:body></w:document>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', xml)
    return path

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.store = boxd.Store(self.home)
        self.store.private.mkdir()
        self.baseline = ['Tier 4+: All', 'Old Film (2000) - 3 stars', 'Original review.']
        document(self.store.private/'source-baseline.docx', self.baseline)
        with (self.store.private/'imported-baseline.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=boxd.FIELDS); w.writeheader()
            w.writerow(dict(Title='Old Film',Year='2000',Rating='3.5',Review='Original review.',Liked='false',WatchedDate='2020-01-01'))
        self.store.init()

    def tearDown(self): self.temp.cleanup()

    def prepare(self, extra):
        return self.store.prepare(document(self.home/'input.docx', self.baseline+extra))

    def film(self, title='Fresh Cinema', redacted=False):
        return [title+' (2026) - 3 stars', '[New film: yes]', '[Letterboxd rating: 3.5]', '[Watched: unknown]',
                '[redact review for upload]' if redacted else 'Great & "fun" <movie>.']

    def test_baseline_no_duplicate(self):
        self.assertIn('No new films', self.prepare([]))
        self.assertFalse(list((self.home/'exports').rglob('*.csv')))
        with self.assertRaises(boxd.Problem): self.store.init()

    def test_edit_and_redact_never_imported(self):
        for text in ['Rewritten review.', '[REDACT REVIEW FOR UPLOAD]']:
            path = document(self.home/'edit.docx', self.baseline[:2]+[text])
            self.assertIn('1 existing entries', self.store.prepare(path))
            self.assertFalse(list((self.home/'exports').rglob('*.csv')))

    def test_partial_confirmation_and_remainder(self):
        self.prepare(self.film()+self.film('Another Picture'))
        s = self.store.load(); batch = s['pending']
        self.assertEqual(len(s['imported']), 1)
        with self.assertRaises(boxd.Problem): self.prepare([])
        self.store.confirm(batch, only='1')
        self.assertEqual(len(self.store.load()['imported']), 2)
        self.store.discard(batch)
        self.prepare(self.film()+self.film('Another Picture'))
        s = self.store.load()
        self.assertEqual(len(s['batches'][s['pending']]['items']), 1)
        self.assertEqual(s['batches'][s['pending']]['items'][0]['row']['Title'], 'Another Picture')

    def test_full_confirmation_and_redaction(self):
        self.prepare(self.film(redacted=True))
        s=self.store.load(); batch=s['pending']
        self.assertEqual(s['batches'][batch]['items'][0]['row']['Review'], '')
        self.store.confirm(batch, all_rows=True)
        self.assertIsNone(self.store.load()['pending'])
        self.assertIn('No new films', self.prepare(self.film(redacted=True)))
        with self.assertRaises(boxd.Problem): self.store.confirm(batch, all_rows=True)

    def test_metadata_required_and_invalid(self):
        for tail in [['New Title (2026) - 3 stars', 'Hi'], self.film()+['[Watched: 2026-13-01]']]:
            try:
                result = self.prepare(tail)
                self.assertIn('No CSV created', result)
            except boxd.Problem:
                pass
        self.assertIsNone(self.store.load()['pending'])

    def test_malformed_heading_and_duplicates(self):
        for tail in [['New title - 3 stars','text'], ['Old Film (2000) - 3 stars','rewatch']]:
            with self.assertRaises(boxd.Problem): self.prepare(tail)

    def test_rename_and_alias(self):
        result = self.prepare(self.film('Old Film').copy())
        self.assertIn('No CSV created', result)
        self.store.alias('renamedfilm:2000', 'oldfilm:2000')
        path = document(self.home/'renamed.docx',['Renamed Film (2000) - 3 stars', 'Original review.'])
        self.assertIn('No new films', self.store.prepare(path))

    def test_tamper_and_corruption(self):
        self.prepare(self.film()); s=self.store.load(); batch=s['pending']
        path = self.home/'exports'/batch/'new-films.csv'; path.write_text('changed')
        with self.assertRaises(boxd.Problem): self.store.confirm(batch, all_rows=True)
        self.assertEqual(len(self.store.load()['imported']), 1)
        self.store.path.write_text('broken')
        with self.assertRaises(boxd.Problem): self.store.load()
        self.assertTrue(list((self.store.private/'backups').glob('*.json')))

    def test_unicode_csv_and_escaping(self):
        self.prepare(self.film('Étrange, cinéma'))
        s=self.store.load(); b=s['batches'][s['pending']]
        with (self.home/'exports'/b['id']/'new-films.csv').open(newline='') as f: rows=list(csv.DictReader(f))
        self.assertEqual(rows[0]['Title'], 'Étrange, cinéma')
        self.assertEqual(rows[0]['Review'],'Great &amp; &quot;fun&quot; &lt;movie&gt;.')

    def test_lock(self):
        with self.store:
            with self.assertRaises(boxd.Problem):
                with boxd.Store(self.home): pass
        self.assertFalse(self.store.lock.exists())

if __name__ == '__main__': unittest.main()
