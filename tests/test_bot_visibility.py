"""Visibility controls must never change money or weaken owner permissions."""
import unittest
import bot_visibility as visible
import test_task_bot as base


class VisibilityTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send

    def test_stars_hidden_from_buttons_and_existing_callbacks(self):
        self.c.execute("UPDATE bot_visibility_flags SET visible=0 WHERE key='stars'")
        self.c.raw.commit()
        menu=self.send(2,action='deposit')
        self.assertNotIn('Telegram Stars',menu['text'])
        self.assertNotIn('bot:topup:stars',str(menu['reply_markup']))
        self.assertIn('скрыт',self.send(2,action='topup:stars')['text'])
        section=self.send(1,action='admin:visibility:finance')
        self.assertIn('bot:admin:visibility:toggle:stars',str(section))
        self.send(1,action='admin:visibility:toggle:stars')
        menu=self.send(2,action='deposit')
        self.assertIn('bot:topup:stars',str(menu['reply_markup']))
        self.assertIn('Курс',self.send(2,action='topup:stars')['text'])

    def test_old_stars_input_cannot_create_new_invoice_after_hiding(self):
        self.send(2,action='topup:stars')
        self.c.execute("UPDATE bot_visibility_flags SET visible=0 WHERE key='stars'")
        self.c.raw.commit()
        result=self.send(2,'10')
        self.assertNotEqual(result['method'],'sendInvoice')
        self.assertFalse(self.c.execute('SELECT 1 FROM bot_wallet_stars').fetchone())

    def test_main_menu_visibility_and_stale_text(self):
        self.send(1,action='admin:visibility:toggle:main_earn')
        screen=self.send(2,'/menu')
        self.assertNotIn('🚀 Заработать',str(screen['reply_markup']))
        self.assertIn('скрыт',self.send(2,'🚀 Заработать')['text'])
        self.send(1,action='admin:visibility:toggle:main_earn')
        self.assertIn('🚀 Заработать',str(self.send(2,'/menu')['reply_markup']))

    def test_admin_menu_is_deduplicated_and_sections_are_clear(self):
        root=self.send(1,action='admin')
        self.assertIn('bot:admin:section:finance',str(root))
        self.assertIn('bot:admin:section:tasks',str(root))
        self.assertIn('bot:admin:section:manage',str(root))
        manage=self.send(1,action='admin:section:manage')
        self.assertIn('bot:admin:visibility',str(manage))
        self.assertNotIn('bot:admin:section:finance',str(manage))
        finance=self.send(1,action='admin:section:finance')
        self.assertIn('bot:admin:paymethods',str(finance))
        self.assertIn('bot:admin:topupsettings',str(finance))
        self.assertEqual(finance['text'].count('💰'),1)
        self.assertIn('Доступ',self.send(2,action='admin:visibility')['text'])

    def test_hidden_wallet_actions_do_not_mutate_balance(self):
        self.send(1,action='admin:visibility:toggle:wallet_deposit')
        self.send(1,action='admin:visibility:toggle:wallet_withdraw')
        card=self.send(2,action='cabinet')
        markup=str(card['reply_markup'])
        self.assertNotIn('bot:deposit',markup)
        self.assertNotIn('bot:withdraw',markup)
        self.assertIn('скрыт',self.send(2,action='deposit')['text'])
        self.assertIn('скрыт',self.send(2,action='withdraw')['text'])
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_payouts").fetchone()['n'],0)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_wallet_stars").fetchone()['n'],0)
