import unittest
from html.parser import HTMLParser
from pathlib import Path

class CheckTags(HTMLParser):
 def __init__(self):
  super().__init__(); self.stack=[]; self.errors=[]; self.ids=[]
 def handle_starttag(self,tag,attrs):
  if tag in {"div","details","section","button","summary","h1","h2","p","span","nav"}:
   self.stack.append(tag)
  for k,v in attrs:
   if k=="id": self.ids.append(v)
 def handle_endtag(self,tag):
  if tag in {"div","details","section","button","summary","h1","h2","p","span","nav"}:
   if not self.stack or self.stack[-1]!=tag:self.errors.append((tag,self.stack[-4:]))
   elif self.stack:self.stack.pop()

class UnifiedFarmScreens(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.page=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
 def test_panel_markup_balanced(self):
  for name in ("farm","coop","storage"):
   block=self.page.split('<section id="'+name+'"',1)[1].split("</section>",1)[0]
   # Browser HTML may include void tags; check layout containers and details.
   start=block.count("<details");end=block.count("</details>")
   self.assertEqual(start,end,(name,"details"))
   self.assertEqual(block.count("<div"),block.count("</div>"),(name,"divs"))
 def test_controls_and_bindings_preserved(self):
  for key in ('id="coop-birds-pane"','id="coop-incubator-pane"','id="storage-summary"','id="auto-coop"','id="coop-harvest"','id="next-harvest"'):
   self.assertIn(key,self.page)
 def test_canonical_production_copy(self):
  self.assertIn("≈ 30 дней",self.page)
  self.assertIn("4 монеты/сутки",self.page)
  self.assertIn("Каждая сытая курица производит одно яйцо за 6 часов",self.page)
  self.assertNotIn("≈ 10 дней",self.page)
 def test_single_dom_ids(self):
  parser=CheckTags();parser.feed(self.page)
  self.assertEqual(len(parser.ids),len(set(parser.ids)))

if __name__=="__main__": unittest.main()
