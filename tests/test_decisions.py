import copy
import json
import unittest
import test_boxd
from test_boxd import boxd
from decisions import make_row, rating_for, year_for

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.rules={'tier_ratings':{'Tier 1':5,'Tier 2':5,'Tier 3':4.5},'liked_tiers':['Tier 1','Tier 2'],
                    'numerical_ratings':{'0.5':.5,'1':1,'1.5':1.5,'2':2.5,'2.5':3,'3':3.5,'3.5':4},
                    'historical_order':['a:2000','b:2001','c:2002'],
                    'watch_partitions':[{'first_key':'a:2000','year':2020},{'first_key':'c:2002','year':2021}]}

    def test_numerical_and_tier_rules(self):
        for old, expected in [(.5,.5),(1,1),(1.5,1.5),(2,2.5),(2.5,3),(3,3.5),(3.5,4)]:
            self.assertEqual(rating_for({'old':old,'tier':'Tier 4+'},self.rules,{})[0],expected)
        for tier, expected in [('Tier 1',5),('Tier 2',5),('Tier 3',4.5)]:
            self.assertEqual(rating_for({'old':4,'tier':tier},self.rules,{})[0],expected)

    def test_exception_overrides_rule(self):
        self.assertEqual(rating_for({'old':2,'tier':'Tier 4+'},self.rules,{'rating':{'final':2,'reason':'approved stay'}})[0],2)

    def test_boundary_and_explicit_unknown(self):
        self.assertEqual(year_for('b:2001',self.rules,{})[0],2020)
        self.assertEqual(year_for('c:2002',self.rules,{})[0],2021)
        self.assertIsNone(year_for('b:2001',self.rules,{'watched':{'year':None,'reason':'unknown'}})[0])
        self.assertEqual(year_for('c:2002',self.rules,{'watched':{'year':2013,'reason':'first watch'}})[0],2013)

class ChangedPolicyTests(unittest.TestCase):
    setUp = test_boxd.MaintenanceTests.setUp
    tearDown = test_boxd.MaintenanceTests.tearDown
    prepare = test_boxd.MaintenanceTests.prepare
    def test_changed_decisions_report_existing_film_without_new_csv(self):
        path=self.store.private/'decisions.json'
        path.write_text(json.dumps({'films':{'oldfilm:2000':{'rating':{'final':4,'reason':'new preference'},'watched':{'year':2019,'reason':'correction'}}}}))
        before=self.store.path.read_bytes()
        self.assertIn('1 existing entries',self.prepare([]))
        report=list((self.home/'exports').glob('report-*.md'))[0].read_text()
        self.assertIn('edit Rating',report)
        self.assertIn('edit WatchedDate',report)
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertFalse(list((self.home/'exports').rglob('*.csv')))
