"""The current Google Doc format supplies final ratings and watch years."""
import tempfile
from pathlib import Path
import unittest
from test_boxd import boxd, document
import test_reconcile


class DocumentFormatTests(unittest.TestCase):
    def parse(self, lines):
        with tempfile.TemporaryDirectory() as folder:
            return boxd.parse_docx(document(Path(folder)/'input.docx', lines))

    def test_favourites_and_log_boundaries_have_different_scope(self):
        es = self.parse(['Tier 1: Favourite', 'One (2000) - 5 / 5 stars', '[Watched in 2010]', 'First.',
                         'Tier 3: Iconic', 'Two (2001) - 4.5 / 5 stars', '[Watched in unknown]', 'Second.',
                         'Tier 4+: All', '2024 Log', 'Three (2002) - 3 / 5 stars', 'Third.',
                         'Four (2003) - 2.5 / 5 stars', 'Fourth.', '2020 Log',
                         'Five (2004) - 1 / 5 star', 'Fifth.'])
        rows = [boxd.make_row(e, {}, {}, boxd.review) for e in es]
        self.assertEqual([r['WatchedDate'] for r in rows], ['2010-01-01', '', '2024-01-01', '2024-01-01', '2020-01-01'])
        self.assertEqual([r['Rating'] for r in rows], ['5', '4.5', '3', '2.5', '1'])
        self.assertEqual([r['Liked'] for r in rows], ['true', 'false', 'false', 'false', 'false'])
        self.assertEqual([r['Review'] for r in rows], ['First.', 'Second.', 'Third.', 'Fourth.', 'Fifth.'])

    def test_missing_year_does_not_fall_back_to_old_decisions(self):
        es = self.parse(['Tier 1', 'One (2000) - 5 / 5 stars', '[Watched in 2020]',
                         'Two (2001) - 4 / 5 stars'])
        with self.assertRaisesRegex(boxd.Problem, 'Missing watched year'):
            boxd.make_row(es[1], {}, {}, boxd.review)

    def test_misplaced_brackets_preserve_redaction_and_report_warning(self):
        e, = self.parse(['Tier 3', 'Example (1994) - 4.5 / 5 stars', '[Watched in 2010',
                         '[redact review for upload]]', 'Private text.'])
        self.assertEqual(boxd.review(e), '')
        self.assertEqual(boxd.metadata(e)['WatchedDate'], '2010-01-01')
        self.assertEqual(len(e['warnings']), 2)

    def test_bracket_boundaries_unknown_and_explicit_date_override(self):
        es = self.parse(['Tier 4+: All', '[Watched in 2024]', 'One (2000) - 4 / 5 stars',
                         '[Watched: 2023-06-01]', 'Review.', '[Watched in unknown]',
                         'Two (2001) - 3 / 5 stars', 'Other.'])
        self.assertEqual([boxd.metadata(e)['WatchedDate'] for e in es], ['2023-06-01', ''])
        self.assertEqual(boxd.review(es[0]), 'Review.')

    def test_current_reviews_use_single_breaks_and_keep_bullets(self):
        e, = self.parse(['Tier 4+', '2026 Log', 'Example (2000) - 4 / 5 stars',
                         'First & best.', 'Second point.'])
        e['bullets'] = [True, True]
        self.assertEqual(boxd.review(e), '• First &amp; best.<br>• Second point.')

    def test_bad_rating_and_control_markers_stop(self):
        for heading in ['Example (2000) - 4.2 / 5 stars', 'Example (2000) - 6 / 5 stars',
                        'Example (2000) - 3 / 4 stars']:
            with self.assertRaises(boxd.Problem):
                for e in self.parse(['Tier 4+', '2020 Log', heading]):
                    boxd.metadata(e)


class CurrentFormatSyncTests(unittest.TestCase):
    setUp = test_reconcile.ReconcileTests.setUp
    tearDown = test_reconcile.ReconcileTests.tearDown
    account = test_reconcile.ReconcileTests.account
    run_sync = test_reconcile.ReconcileTests.run_sync
    rows = test_reconcile.ReconcileTests.rows
    def test_current_document_overrides_historical_policy_in_review_update(self):
        folder, report = self.run_sync(['Tier 4+: All', '2020 Log',
                                       'Old Film (2000) - 4.5 / 5 stars', 'Updated.'])
        self.assertIn('current film rating 3.5 → 4.5', report)
        self.assertEqual(self.rows(folder, 'review-updates.csv')[0], {
            'LetterboxdURI': 'https://boxd.it/review1', 'WatchedDate': '2020-01-01', 'Review': 'Updated.'})

    def test_new_film_needs_no_separate_rating_or_date_marker(self):
        folder, _ = self.run_sync(self.baseline + ['2026 Log', 'Fresh Film (2026) - 4 / 5 stars',
                                                  '[New film: yes]', 'New review.'])
        row, = self.rows(folder, 'new-films.csv')
        self.assertEqual(row['Rating'], '4')
        self.assertEqual(row['WatchedDate'], '2026-01-01')
        self.assertEqual(row['Review'], 'New review.')
