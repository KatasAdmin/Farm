"""Owner console: permissions, persisted copy, contract snapshots and money conservation."""
import unittest
import bot_copy as copy
import bot_admin as admin
import task_bot as bot
import test_task_bot as base


class AdminTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    balance=base.TaskBotTests.balance
    credit=base.TaskBotTests.credit
    task=base.TaskBotTests.task

    def field(self,key,value):
        self.send(1,action='admin:field:'+key)
        return self.send(1,value)

    def payout(self,amount='5'):
        self.send(2,action='withdraw'); self.send(2,amount)
        result=self.send(2,'TEST BANK RECIPIENT')
        self.send(2,action='confirm_payout')
        return self.c.execute('SELECT * FROM bot_payouts ORDER BY created DESC LIMIT 1').fetchone(),result

    def copy_row(self,kind,original):
        return self.c.execute('SELECT * FROM bot_copy_catalog WHERE kind=%s AND original=%s',(kind,original)).fetchone()

    def customize(self,key,body):
        self.send(1,action='admin:copyedit:'+key)
        preview=self.send(1,body)
        data=bot.state(self.c,1)['data']
        self.send(1,action='admin:copysave:'+data['nonce'])
        return preview

    def test_clean_sections_and_owner_entry(self):
        panel=self.send(1,action='admin')
        self.assertNotIn('/bot',panel['text'])
        for section in ('admin:copy','admin:money','admin:tickets','admin:economy','admin:settings:limits'):
            self.assertIn('bot:'+section,str(panel['reply_markup']))
        self.assertIn('bot:admin',str(self.send(1,action='cabinet')))
        self.assertNotIn('bot:admin',str(self.send(2,action='cabinet')))
        for action in ('admin','admin:copy','admin:field:daily','admin:money:credit'):
            self.assertIn('Доступ',self.send(2,action=action)['text'])

    def test_forged_admin_state_denied(self):
        bot.state(self.c,2,'admin_field',{'key':'daily'}); self.c.raw.commit()
        result=self.send(2,'50')
        self.assertIn('Доступ',result['text'])
        self.assertEqual(self.c.execute('SELECT daily FROM bot_settings').fetchone()['daily'],50)

    def test_individual_settings_validate_and_keep_old_order_terms(self):
        tid=self.task(count='1')
        terms=dict(self.c.execute('SELECT * FROM bot_task_terms WHERE task=%s',(tid,)).fetchone())
        self.field('price_channel','1.20')
        self.field('ref1','4.5')
        self.field('daily','0.75')
        self.field('days','10'); self.field('multiplier','3')
        self.assertEqual(self.c.execute('SELECT * FROM bot_task_terms WHERE task=%s',(tid,)).fetchone(),terms)
        self.assertEqual(bot.bot_economy.quote(self.c,'channel')['cost'],120)
        self.assertEqual(bot.bot_economy.quote(self.c,'channel')['reward'],96)
        self.assertEqual(bot.bot_economy.config(self.c)['ref1'],450)
        self.assertIn('покрывать',self.field('ref1','90')['text'])
        self.assertEqual(bot.bot_economy.config(self.c)['ref1'],450)
        self.assertEqual(self.c.execute('SELECT daily FROM bot_settings').fetchone()['daily'],75)

    def test_limits_used_and_invalid_settings_rollback(self):
        self.field('max_stars','5')
        self.send(3,action='topup:stars')
        self.assertNotEqual(self.send(3,'6')['method'],'sendInvoice')
        self.assertEqual(self.send(3,'5')['method'],'sendInvoice')
        self.field('withdraw_min','10')
        self.assertIn('не может',self.field('withdraw_max','5')['text'])
        self.assertEqual(admin.limits(self.c)['withdraw_max'],100000000)
        self.assertIn('меньше',self.field('withdraw_fee','100')['text'])
        self.assertEqual(admin.limits(self.c)['withdraw_fee'],0)

    def test_payout_fee_snapshot_net_cash_and_replay(self):
        self.credit(value='10')
        self.field('withdraw_fee','10')
        p,preview=self.payout()
        self.assertIn('Комиссия: 0,50 грн',preview['text'])
        self.assertIn('К выплате: 4,50 грн',preview['text'])
        self.assertEqual(self.balance(2),500)
        self.assertEqual(admin.net(self.c,p),450)
        self.assertEqual(bot.liability(self.c),1000)
        self.field('withdraw_fee','20')
        self.send(1,action='admin:payref:'+p['id']); self.send(1,'bank-payout-real')
        self.send(1,action='admin:payconfirm',event=888)
        self.send(1,action='admin:payconfirm',event=888)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],550)
        self.assertEqual(bot.liability(self.c),500)
        self.assertIn('Выведено всего: 4,50 грн',self.send(2,action='cabinet')['text'])
        self.assertIn('4,50 грн',self.send(2,action='about:stats')['text'])

    def test_cancel_and_reject_return_full_gross(self):
        self.credit(); self.field('withdraw_fee','10')
        p,_=self.payout(); self.send(2,action='cancelpayout')
        self.assertEqual(self.balance(2),1000)
        p,_=self.payout(); self.send(1,action='admin:rejectpayout:'+p['id'])
        self.assertEqual(self.balance(2),1000)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],1000)

    def test_legacy_payout_without_snapshot_preserves_full_amount(self):
        self.credit(); p,_=self.payout()
        self.c.execute('DELETE FROM bot_payout_terms WHERE id=%s',(p['id'],)); self.c.raw.commit()
        self.field('withdraw_fee','30')
        self.assertEqual(admin.net(self.c,p),500)

    def test_money_wizard_nonce_and_bank_reference_uniqueness(self):
        self.send(1,action='admin:money:credit')
        for value in ('2','3.50','bank-credit-unique'):self.send(1,value)
        d=bot.state(self.c,1)['data']
        self.assertEqual(self.balance(2),0)
        self.send(1,action='admin:moneyconfirm:'+d['nonce'])
        self.send(1,action='admin:moneyconfirm:'+d['nonce'])
        self.assertEqual(self.balance(2),350)
        self.credit(value='10',ref='bank-credit-unique')
        self.assertEqual(self.balance(2),350)

    def test_catalog_seeded_without_visiting_screens_and_no_user_data(self):
        rows=self.c.execute('SELECT * FROM bot_copy_catalog').fetchall()
        self.assertGreater(len(rows),350)
        self.assertTrue(any('Пополнение через Stars' in r['original'] for r in rows))
        self.assertFalse(any('TEST BANK' in r['original'] for r in rows))
        self.assertEqual(len([r for r in rows if r['kind']=='menu']),6)

    def test_menu_aliases_survive_repeated_rename_reset_and_restart(self):
        row=self.copy_row('menu','🚀 Заработать')
        self.customize(row['key'],'💼 Работа')
        self.assertIn('💼 Работа',str(self.send(3,'/start')['reply_markup']))
        self.assertIn('Как хочешь заработать',self.send(3,'💼 Работа')['text'])
        self.customize(row['key'],'💎 Доход')
        bot.initialize(self.c); self.c.raw.commit()
        self.assertIn('Как хочешь заработать',self.send(3,'💼 Работа')['text'])
        self.assertIn('Как хочешь заработать',self.send(3,'💎 Доход')['text'])
        self.send(1,action='admin:copyreset:'+row['key'])
        self.assertIn('🚀 Заработать',str(self.send(3,'/start')['reply_markup']))
        self.assertIn('Как хочешь заработать',self.send(3,'💎 Доход')['text'])

    def test_duplicate_menu_rejected_and_button_action_stable(self):
        row=self.copy_row('menu','🚀 Заработать')
        with self.assertRaises(bot.UserError):copy.save(self.c,1,row['key'],'📣 Продвижение')
        button=self.copy_row('button','➕ Пополнить')
        self.customize(button['key'],'💳 Внести деньги')
        result=self.send(3,action='cabinet')
        first=result['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(first,dict(text='💳 Внести деньги',callback_data='bot:deposit'))
        self.assertIn('Выбери способ',self.send(3,action='deposit')['text'])

    def test_template_real_values_safe_html_and_restore(self):
        self.send(3,action='earn')
        row=self.c.execute("SELECT * FROM bot_copy_catalog WHERE kind='text' AND original LIKE '🚀 <b>Как хочешь%' ").fetchone()
        body=row['original'].replace('Как хочешь заработать?','Задания для тебя')
        self.customize(row['key'],body)
        result=self.send(3,action='earn')
        self.assertIn('Задания для тебя',result['text'])
        self.assertIn('0,00 грн',result['text'])
        self.assertNotIn('{v',result['text'])
        for bad in (body.replace('{v0}','0'),body+'<a href="x">unsafe</a>',body.replace('{v0}','{v0.__class__}'),body.replace('{v0}','{v0:1000000}')):
            with self.assertRaises(bot.UserError):copy.validate(self.c,row,bad)
        history=self.c.execute('SELECT * FROM bot_copy_history WHERE key=%s ORDER BY created DESC',(row['key'],)).fetchone()
        self.send(1,action='admin:copyrestore:'+history['id'])
        self.assertIn('Как хочешь заработать',self.send(3,action='earn')['text'])

    def test_dynamic_numbers_remain_live_after_button_rename(self):
        self.send(3,action='earn')
        row=self.c.execute("SELECT * FROM bot_copy_catalog WHERE kind='button' AND section='public' AND original LIKE '🎁 Бонус%'").fetchone()
        self.customize(row['key'],row['original'].replace('Бонус','Подарок'))
        self.field('daily','0.75')
        result=self.send(3,action='earn')
        self.assertIn('Подарок',str(result['reply_markup']))
        self.assertIn('0,75 грн',str(result['reply_markup']))

    def test_button_copy_cannot_be_changed_by_nonowner(self):
        row=self.copy_row('button','➕ Пополнить')
        self.assertIn('Доступ',self.send(2,action='admin:copyedit:'+row['key'])['text'])
        self.assertIsNone(self.c.execute('SELECT custom FROM bot_copy_catalog WHERE key=%s',(row['key'],)).fetchone()['custom'])

    def test_search_cyrillic_and_custom_text(self):
        row=self.copy_row('menu','🚀 Заработать')
        self.customize(row['key'],'💼 Мои задания')
        self.send(1,action='admin:copysearch')
        result=self.send(1,'мои ЗАДАНИЯ')
        self.assertIn('bot:admin:copyentry:'+row['key'],str(result['reply_markup']))
        self.assertIsNone(bot.state(self.c,1))

    def test_editing_cannot_disable_validation_or_turn_menu_into_command(self):
        row=self.copy_row('menu','🚀 Заработать')
        for bad in ('/admin','123','two\nlines','\x01text'):
            with self.assertRaises(bot.UserError):copy.validate(self.c,row,bad)
        key=self.c.execute("SELECT key FROM bot_copy_catalog WHERE kind='text' AND original LIKE 'Количество Stars:%'").fetchone()['key']
        self.customize(key,'Укажи количество в пределах 1–{v0}.')
        self.field('max_stars','5')
        self.send(3,action='topup:stars')
        self.assertIn('Укажи количество',self.send(3,'6')['text'])
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_wallet_stars').fetchone()['n'],0)

    def test_bootstrap_preserves_saved_values_and_catalog_overrides(self):
        self.field('daily','0.80'); self.field('withdraw_fee','2.5')
        row=self.copy_row('menu','🚀 Заработать'); self.customize(row['key'],'💼 Работа')
        bot.initialize(self.c); self.c.raw.commit()
        self.assertEqual(admin.limits(self.c)['withdraw_fee'],250)
        self.assertEqual(self.c.execute('SELECT daily FROM bot_settings').fetchone()['daily'],80)
        self.assertEqual(self.c.execute('SELECT custom FROM bot_copy_catalog WHERE key=%s',(row['key'],)).fetchone()['custom'],'💼 Работа')
