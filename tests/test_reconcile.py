import csv
import json
from pathlib import Path
import unittest
import zipfile

import test_boxd as fixtures
from test_boxd import boxd, document
import subprocess
import sys
import reconcile


class ReconcileTests(unittest.TestCase):
    setUp = fixtures.MaintenanceTests.setUp
    tearDown = fixtures.MaintenanceTests.tearDown

    def account(self, review='Original review.', rating='3.5', entry_rating='3.5', date='2020-01-01', extra=None):
        folder = self.home/'account'; folder.mkdir(exist_ok=True)
        film = dict(Name='Old Film',Year='2000', **{'Letterboxd URI':'https://boxd.it/film1'})
        entry = dict(film, **{'Letterboxd URI':'https://boxd.it/review1','Rating':entry_rating,'Review':review,'Watched Date':date})
        rows = {'watched.csv':[film], 'ratings.csv':[dict(film,Rating=rating)],
                'reviews.csv':[entry] if review is not None else [], 'diary.csv':[entry]}
        for name, values in (extra or {}).items(): rows[name].extend(values)
        fields = {'watched.csv':['Name','Year','Letterboxd URI'],
                  'ratings.csv':['Name','Year','Letterboxd URI','Rating'],
                  'reviews.csv':['Name','Year','Letterboxd URI','Rating','Review','Watched Date'],
                  'diary.csv':['Name','Year','Letterboxd URI','Rating','Watched Date']}
        for name, values in rows.items():
            with (folder/name).open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=fields[name],extrasaction='ignore')
                writer.writeheader(); writer.writerows(values)
        return folder

    def run_sync(self, paragraphs=None, export=None):
        doc=document(self.home/'current.docx',paragraphs or self.baseline)
        before=self.store.path.read_bytes()
        result=reconcile.prepare(self.store,doc,export or self.account(),boxd)
        self.assertEqual(before,self.store.path.read_bytes())
        report=Path(result.split('Report: ')[1].split('\n')[0])
        return report.parent,report.read_text()

    def rows(self, folder, name):
        with (folder/name).open(newline='',encoding='utf-8') as f: return list(csv.DictReader(f))

    def test_review_update_uses_entry_uri_original_date_no_rating(self):
        folder,_=self.run_sync(self.baseline[:2]+['A revised & "quoted" review.'])
        self.assertEqual(self.rows(folder,'review-updates.csv'),[{
            'LetterboxdURI':'https://boxd.it/review1','WatchedDate':'2020-01-01',
            'Review':'A revised &amp; &quot;quoted&quot; review.'}])
        self.assertFalse((folder/'new-films.csv').exists())

    def test_fresh_export_clears_changes_without_confirm(self):
        paragraphs=self.baseline[:2]+['Updated.']
        self.run_sync(paragraphs)
        folder,_=self.run_sync(paragraphs,self.account(review='Updated.'))
        self.assertFalse(list(folder.glob('*.csv')))

    def test_live_change_detected_even_when_document_equals_import_history(self):
        folder,_=self.run_sync(export=self.account(review='Changed on Letterboxd.'))
        self.assertEqual(self.rows(folder,'review-updates.csv')[0]['Review'],'Original review.')

    def test_rating_only_manual_for_current_and_entry(self):
        folder,report=self.run_sync(self.baseline+['[Letterboxd rating: 4.5]'])
        self.assertFalse(list(folder.glob('*.csv')))
        self.assertIn('current film rating 3.5 → 4.5',report)
        self.assertIn('entry rating 3.5 → 4.5',report)

    def test_review_update_does_not_include_simultaneous_rating_change(self):
        folder,report=self.run_sync(self.baseline[:2]+['Updated.','[Letterboxd rating: 4.5]'])
        self.assertNotIn('Rating',self.rows(folder,'review-updates.csv')[0])
        self.assertIn('entry rating',report)

    def test_redaction_date_change_and_unknown_date_are_manual(self):
        for paragraphs,account,reason in [
            (self.baseline+['[REDACT REVIEW FOR UPLOAD]'],{},'clear published review'),
            (self.baseline[:2]+['Updated.','[Watched: 2021]'],{},'watched date'),
            (self.baseline[:2]+['Updated.','[Watched: unknown]'],{'date':''},'undated review')]:
            folder,report=self.run_sync(paragraphs,self.account(**account))
            self.assertFalse(list(folder.glob('*.csv')))
            self.assertIn(reason,report)

    def test_deleted_review_is_not_restored(self):
        folder,report=self.run_sync(export=self.account(review=None))
        self.assertFalse(list(folder.glob('*.csv')))
        self.assertIn('review absent',report)

    def test_multiple_entries_do_not_pick_arbitrary_review(self):
        second=dict(Name='Old Film',Year='2000',Rating='3.5',Review='Second.',**{'Letterboxd URI':'https://boxd.it/review2','Watched Date':'2021-01-01'})
        folder,report=self.run_sync(self.baseline[:2]+['Updated.'],self.account(extra={'reviews.csv':[second],'diary.csv':[second]}))
        self.assertFalse(list(folder.glob('*.csv')))
        self.assertIn('multiple review/diary',report)

    def test_new_film_then_export_prevents_duplicate_even_without_history(self):
        paragraphs=self.baseline+['Fresh Cinema (2026) - 3 stars','[New film: yes]',
            '[Letterboxd rating: 4]','[Watched: 2026]','Nice.']
        folder,_=self.run_sync(paragraphs)
        self.assertEqual(self.rows(folder,'new-films.csv')[0]['Rating'],'4')
        film=dict(Name='Fresh Cinema',Year='2026',Rating='4',**{'Letterboxd URI':'https://boxd.it/fresh'})
        rv=dict(film,Review='Nice.',**{'Letterboxd URI':'https://boxd.it/freshreview','Watched Date':'2026-01-01'})
        folder,_=self.run_sync(paragraphs,self.account(extra={'watched.csv':[film],'ratings.csv':[film],'reviews.csv':[rv],'diary.csv':[rv]}))
        self.assertFalse(list(folder.glob('*.csv')))
        folder,report=self.run_sync(paragraphs,self.account())
        self.assertFalse(list(folder.glob('*.csv')))
        self.assertIn('Previously recorded film missing',report)

    def test_zip_nested_root_ignores_deleted_and_rejects_incomplete(self):
        account=self.account(review='Live change.')
        archive=self.home/'account.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for p in account.iterdir():z.write(p,'export/'+p.name)
            z.writestr('export/deleted/reviews.csv','bad,data')
        folder,_=self.run_sync(export=archive)
        self.assertTrue((folder/'review-updates.csv').exists())
        with zipfile.ZipFile(archive,'w') as z:z.write(account/'ratings.csv','ratings.csv')
        with self.assertRaises(boxd.Problem):self.run_sync(export=archive)

    def test_verified_mapping_for_translated_title(self):
        account=self.account()
        for p in account.iterdir():p.write_text(p.read_text().replace('Old Film','Translated Film'))
        folder,report=self.run_sync(self.baseline[:2]+['Updated.'],account)
        self.assertIn('Previously recorded film missing',report)
        self.assertFalse(list(folder.glob('*.csv')))
        (self.store.private/'film-identities.json').write_text(json.dumps({'oldfilm:2000':'https://boxd.it/film1'}))
        folder,_=self.run_sync(self.baseline[:2]+['Updated.'],account)
        self.assertTrue((folder/'review-updates.csv').exists())

    def test_approved_correction_uses_verified_film_uri_and_current_document(self):
        account = self.account()
        _, hashes = reconcile.read_export(account, boxd.Problem)
        approval = {'oldfilm:2000': {'title': 'Correct Film', 'year': '2000',
            'uri': 'https://letterboxd.com/film/correct-film/', 'kind': 'correction',
            'wrong_uri': 'https://boxd.it/film1', 'export_hashes': hashes}}
        path = self.store.private/'import-approvals.json'
        path.write_text(json.dumps(approval))
        paragraphs = ['Tier 4+', '2020 Log', 'Old Film (2000) - 4 / 5 stars', 'Current review.']
        folder, report = self.run_sync(paragraphs, account)
        row, = self.rows(folder, 'corrected-films.csv')
        self.assertEqual(row['LetterboxdURI'], approval['oldfilm:2000']['uri'])
        self.assertEqual(row['Review'], 'Current review.')
        self.assertEqual(row['Rating'], '4')
        self.assertIn('delete misplaced review https://boxd.it/review1', report)
        self.assertFalse((folder/'review-updates.csv').exists())
        # A later export that still lacks the approved film must not re-add it.
        folder, report = self.run_sync(paragraphs, self.account(rating='2'))
        self.assertFalse(list(folder.glob('*.csv')))
        self.assertIn('different export', report)
        # Once the correct film appears, normal reconciliation resumes.
        account = self.account(review='Current review.', rating='4', entry_rating='4')
        for f in account.iterdir():
            f.write_text(f.read_text().replace('Old Film', 'Correct Film'))
        folder, report = self.run_sync(paragraphs, account)
        self.assertFalse(list(folder.glob('*.csv')))

    def test_combined_csv_preserves_review_update_without_rating(self):
        paragraphs = self.baseline[:2] + ['Updated.', '2026 Log',
            'Fresh Film (2026) - 4 / 5 stars', '[New film: yes]', 'New review.']
        folder, _ = self.run_sync(paragraphs)
        rows = self.rows(folder, 'upload.csv')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['Rating'], '4')
        self.assertEqual(rows[1]['LetterboxdURI'], 'https://boxd.it/review1')
        self.assertEqual(rows[1]['Rating'], '')
        self.assertEqual(rows[1]['Review'], 'Updated.')

    def test_latest_inputs_ignore_generated_folders_and_office_locks(self):
        import os
        folder = self.home/'incoming'; folder.mkdir()
        with self.assertRaises(boxd.Problem):
            reconcile.latest_inputs(folder, boxd.Problem)
        old = folder/'old.docx'; old.touch(); os.utime(old, (1, 1))
        doc = folder/'new.docx'; doc.touch(); os.utime(doc, (2, 2))
        export = folder/'account.zip'; export.touch()
        (folder/'~$new.docx').touch()
        nested = folder/'sync-old'; nested.mkdir(); (nested/'ignored.docx').touch()
        self.assertEqual(reconcile.latest_inputs(folder, boxd.Problem), (doc, export))
        tied = folder/'tied.docx'; tied.touch(); os.utime(tied, (2, 2))
        with self.assertRaisesRegex(boxd.Problem, 'ambiguous'):
            reconcile.latest_inputs(folder, boxd.Problem)

    def test_cli_requires_both_inputs_and_runs_fresh_comparison(self):
        doc=document(self.home/'current.docx',self.baseline)
        result=subprocess.run([sys.executable,str(Path(boxd.__file__)),'--home',str(self.home),'prepare',str(doc),str(self.account())],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__ == '__main__':unittest.main()
