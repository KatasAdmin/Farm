import unittest
import fields

class FieldEconomyTests(unittest.TestCase):
 def test_prices_and_20_day_payback(self):
  self.assertEqual(fields.FIELD_PRICE,240)
  self.assertEqual(fields.COMBINE_PRICE,200)
  for plots in range(1,501):
   combines=(plots+4)//5
   investment=plots*fields.FIELD_PRICE+combines*fields.COMBINE_PRICE
   grain=fields.rate(plots,combines)
   self.assertEqual(grain*2*20,investment)
 def test_capacity_and_maximum(self):
  self.assertEqual(fields.MAX_FIELDS,500)
  self.assertEqual(fields.MAX_COMBINES,100)
  self.assertEqual(fields.rate(500,100),3500)
  self.assertEqual(fields.rate(1,1),11)
  self.assertEqual(fields.rate(5,1),35)
  self.assertEqual(fields.rate(6,2),46)
  self.assertEqual(fields.rate(0,1),0)
