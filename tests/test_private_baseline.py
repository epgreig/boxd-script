"""Golden-file regression using private local fixtures, never committed reviews.

All fields are generated from DOCX plus editable policy inputs. The expected
CSV is read only by this test, never by the generator or import initializer.
"""
import csv
import io
from pathlib import Path
import shutil
import tempfile
import unittest

from test_boxd import boxd
from decisions import read_policy, make_row

PRIVATE = Path(__file__).resolve().parents[1] / 'private'
CSV = PRIVATE / 'imported-baseline.csv'
DOCX = PRIVATE / 'source-baseline.docx'


@unittest.skipUnless(CSV.exists() and DOCX.exists(), 'Private baseline fixtures are not present')
class PrivateBaselineRegression(unittest.TestCase):
    def test_exact_reconstruction_and_no_repeat_import(self):
        original_bytes = CSV.read_bytes()
        with CSV.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            expected = list(reader)
        entries = boxd.parse_docx(DOCX)
        self.assertEqual(len(entries), 333)
        self.assertEqual(len(expected), 333)

        # Never initialize or mutate the live import state while testing.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'private').mkdir()
            shutil.copy2(DOCX, home / 'private/source-baseline.docx')
            for name in ['rules.json','decisions.json']:
                shutil.copy2(PRIVATE/name,home/'private'/name)
            # No CSV of any kind exists in the generator's temporary home.
            self.assertFalse(list(home.rglob('*.csv')))
            store = boxd.Store(home)
            store.init()
            state = store.load()
            rules, policy = read_policy(home)
            reconstructed = []
            for position, (entry, golden) in enumerate(zip(entries, expected), 1):
                with self.subTest(position=position, title=entry['title']):
                    key = state['aliases'].get(entry['key'], entry['key'])
                    rebuilt = make_row(entry,rules,policy,boxd.review)
                    self.assertEqual(rebuilt, golden)
                    reconstructed.append(rebuilt)

            stream = io.StringIO(newline='')
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(reconstructed)
            self.assertEqual(stream.getvalue().encode('utf-8'), original_bytes,
                             'Reconstructed CSV differs at the byte level')

            self.assertEqual(sum(not r['Review'] for r in reconstructed), 5)
            self.assertEqual(sum(not r['WatchedDate'] for r in reconstructed), 9)
            self.assertEqual(sum(r['Liked'] == 'true' for r in reconstructed), 21)
            by_title = {r['Title']: r for r in reconstructed}
            self.assertEqual(by_title['2001: A Space Odyssey']['Rating'], '4')
            self.assertEqual(by_title['Mirror']['Rating'], '3.5')
            self.assertEqual(by_title['Fargo']['WatchedDate'], '2019-01-01')

            before_state = store.path.read_bytes()
            for _ in range(2):
                result = store.prepare(DOCX)
                self.assertIn('No new films. 0 existing entries', result)
                self.assertFalse(list((home / 'exports').rglob('*.csv')))
                self.assertEqual(store.path.read_bytes(), before_state)


if __name__ == '__main__':
    unittest.main()
