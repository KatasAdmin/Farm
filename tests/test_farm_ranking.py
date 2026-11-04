import unittest
from test_monetag_rewards import AdDB
import farm_ranking
class FarmRanking(unittest.TestCase):
 def test_top_five_use_main_level_and_include_exact_place_outside_top(self):
  c=AdDB();c.execute('CREATE TABLE players(id text,name text,farmer_level int,chickens int)')
  for i in range(12):c.execute('INSERT INTO players VALUES(%s,%s,%s,%s)',(str(i),f'Farmer{i:02}',12-i,9999 if i==11 else 0))
  top,place=farm_ranking.snapshot(c,'11');self.assertEqual(len(top),5);self.assertEqual(place,12)
  self.assertEqual([r['farmer_level'] for r in top],[12,11,10,9,8]);self.assertEqual([r['farm_score'] for r in top],[12,11,10,9,8]);self.assertFalse(any(r['is_me'] for r in top))
 def test_level_ties_have_stable_unique_places(self):
  c=AdDB();c.execute('CREATE TABLE players(id text,name text,farmer_level int)')
  for id,name in [('b','Alpha'),('a','Alpha'),('c','Zed')]:c.execute('INSERT INTO players VALUES(%s,%s,5)',(id,name))
  self.assertEqual([farm_ranking.snapshot(c,id)[1] for id in ('a','b','c')],[1,2,3])

 def test_level_eight_is_sent_to_both_current_and_already_open_clients(self):
  c=AdDB();c.execute('CREATE TABLE players(id text,name text,farmer_level int)')
  c.execute("INSERT INTO players VALUES('me','Katas',8)")
  top,rank=farm_ranking.snapshot(c,'me')
  self.assertEqual((top[0]['farmer_level'],top[0]['farm_score'],rank),(8,8,1))
