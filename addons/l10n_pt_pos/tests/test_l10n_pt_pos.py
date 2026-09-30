from odoo import Command, fields
from odoo.exceptions import RedirectWarning, UserError
from odoo.models import Model
from odoo.tests import tagged
from odoo.tests.common import freeze_time
from odoo.addons.l10n_pt_certification.tests.common import TestL10nPtCommon
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


class TestL10nPtPosCommon(TestL10nPtCommon, TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        category_pt = cls.env['pos.category'].create({'name': 'Test Category'})
        cls.config = cls.basic_config
        cls.config.write({
            'limit_categories': True,
            'iface_available_categ_ids': [Command.set(category_pt.ids)],
        })
        cls.config.payment_method_ids.write({
            'l10n_pt_pos_payment_mechanism': 'TB',
        })
        cls.product1 = cls.env['product.product'].create({
            'name': 'Product 1',
            'available_in_pos': True,
            'list_price': 100,
            'taxes_id': cls.tax_sale_0.ids,
            'pos_categ_ids': [Command.link(category_pt.id)],
        })

    def _create_pos_order(self, date_order="2024-01-01", partner=False):
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=[
                (self.product1, 1.0),
            ],
            customer=partner
        )
        total_amount = order_data['amount_total']
        order_data['payment_ids'] = [(0, 0, {
            'amount': total_amount,
            'name': fields.Datetime.now(),
            'payment_method_id': self.bank_pm1.id,
        })]
        order_data['amount_paid'] = total_amount
        results = self.env['pos.order'].sync_from_ui([order_data])
        order = self.env['pos.order'].browse(results['pos.order'][0]['id'])
        if order.state != 'paid':
            order.action_pos_order_paid()
        if date_order:
            # Bypass the write method of pos.order to change the date_order
            Model.write(order, {'date_order': fields.Date.from_string(date_order)})
        return order


@freeze_time('2024-06-15')
@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nPtPosMiscRequirements(TestL10nPtPosCommon):
    def test_l10n_pt_pos_partner(self):
        """Test misc requirements for partner"""
        self.open_new_session()
        # Cannot change tax number of an existing client with already issued documents.
        # However, missing tax number can only be entered if the field is empty
        # (or filled with generic client tax 999999990)
        partner_a = self.env['res.partner'].create({
            'name': 'Partner A',
            'company_id': self.company_pt.id,
        })
        partner_a.vat = "PT123456789"
        partner_a.vat = "999999990"

        self._create_pos_order(partner=partner_a)

        partner_a.vat = "PT123456789"
        with self.assertRaisesRegex(UserError, "You cannot change the VAT number of a partner that already has issued documents"):
            partner_a.vat = "PT987654321"

    def test_l10n_pt_pos_product(self):
        """Test that we do not allow change ProductDescription if already issued docs"""
        self.open_new_session()
        product = self.product1
        product.name = "Product A2"  # OK

        self._create_pos_order()

        with self.assertRaisesRegex(UserError, "You cannot modify the name of a product that has been used"):
            # Stock picking is triggered before POS order
            product.name = "Product A3"

    def test_l10n_pt_pos_payment_method_missing_mechanism(self):
        """Test that we do not allow opening a session if a payment method lacks a mechanism."""
        pos_payment_method = self.env['pos.payment.method'].create({
            'name': 'Payment method - No mechanism',
            'receivable_account_id': self.company_data['default_account_receivable'].id,
            'journal_id': self.company_data['default_journal_bank'].id,
        })
        self.config.write({'payment_method_ids': [Command.link(pos_payment_method.id)]})
        with self.assertRaises(RedirectWarning) as cm:
            self.open_new_session()
        self.assertEqual(cm.exception.args[0], "All payment methods available for this Point of Sale should have a payment mechanism.")

    def test_l10n_pt_pos_payment_method_missing_series(self):
        """Test that we do not allow opening a session if a bank journal payment method has no AT Series."""
        bank_journal_no_series = self.env['account.journal'].create({
            'name': 'Bank No Series',
            'type': 'bank',
            'code': 'BNKS',
        })
        pos_payment_method = self.env['pos.payment.method'].create({
            'name': 'Payment method - No series',
            'receivable_account_id': self.company_data['default_account_receivable'].id,
            'journal_id': bank_journal_no_series.id,
            'l10n_pt_pos_payment_mechanism': 'TB',
        })
        self.config.write({'payment_method_ids': [Command.link(pos_payment_method.id)]})
        with self.assertRaises(RedirectWarning) as cm:
            self.open_new_session()
        self.assertEqual(cm.exception.args[0], "Payment methods with a bank journal should also have an AT Series defined.")

    def test_l10n_pt_pos_vat_exemptions_reasons(self):
        """Test that _l10n_pt_pos_get_vat_exemptions_reasons works with self.lines."""
        self.open_new_session()
        order = self._create_pos_order()
        reasons = order._l10n_pt_pos_get_vat_exemptions_reasons()
        self.assertIsInstance(reasons, list)

    def test_l10n_pt_pos_invoice_generation_done_state(self):
        """Test that _generate_pos_order_invoice sets order state to 'done' and marks invoice paid."""
        self.open_new_session()
        order = self._create_pos_order()
        with self._mock_sign_records():
            order._generate_pos_order_invoice()
        self.assertEqual(order.state, 'done')
        self.assertTrue(order.account_move)
        self.assertEqual(order.account_move.payment_state, 'paid')
