# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import os
from unittest.mock import patch
from xml.etree import ElementTree as ET

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import float_repr
from odoo.addons.l10n_pt_certification.const import PT_PRODUCT_ID
from odoo.addons.l10n_pt_certification.tests.common import TestL10nPtCommon
from odoo.addons.l10n_pt_certification.wizard import l10n_pt_saft_export_wizard as wizard_module

try:
    import xmlschema
except ImportError:
    xmlschema = None


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nPtSaft(TestL10nPtCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure company has complete Portuguese address
        cls.company_data['company'].write({
            'street': 'Avenida da Liberdade 100',
            'city': 'Lisboa',
            'zip': '1250-145',
            'vat': 'PT500000000',
            'company_registry': '500000000',
        })
        cls.partner_pt = cls.env['res.partner'].create({
            'name': 'Cliente Nacional PT',
            'street': 'Rua do Ouro 1',
            'city': 'Lisboa',
            'zip': '1100-060',
            'country_id': cls.env.ref('base.pt').id,
            'vat': 'PT501234560',
        })
        cls.partner_es = cls.env['res.partner'].create({
            'name': 'Cliente Espanha ES',
            'street': 'Gran Via 1',
            'city': 'Madrid',
            'zip': '28013',
            'country_id': cls.env.ref('base.es').id,
            'vat': 'ESA12345674',
        })

    def test_producer_vat_and_cert_placeholder_raises(self):
        """ Test that export raises UserError when producer VAT or certificate number is unconfigured placeholder. """
        wizard = self.env['l10n_pt.saft.export.wizard'].create({
            'company_id': self.company_data['company'].id,
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })
        with patch.object(wizard_module, 'PT_PRODUCER_VAT', ''):
            with self.assertRaises(UserError) as cm:
                wizard.action_export_saft()
            self.assertIn("Producer", str(cm.exception))

        with patch.object(wizard_module, 'PT_PRODUCER_VAT', '599999993'):
            with patch.object(wizard_module, 'PT_CERTIFICATION_NUMBER', '9999'):
                with self.assertRaises(UserError) as cm:
                    wizard.action_export_saft()
                self.assertIn("Certification Number", str(cm.exception))

    def test_saft_wizard_validation_and_export(self):
        """Test SAF-T wizard export with exemptions, credit notes, foreign partners, and product codes."""

        # 1. Create duplicate default_code products
        prod_a = self.env['product.product'].create({
            'name': 'Serviço A',
            'default_code': 'PROD_DUP',
            'type': 'service',
        })
        prod_b = self.env['product.product'].create({
            'name': 'Artigo B',
            'default_code': 'PROD_DUP',
            'type': 'consu',
        })

        # 2. Create invoice with regular tax and exemption
        tax_exempt = self.env['account.tax'].search([
            ('company_id', '=', self.company_data['company'].id),
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 0.0),
        ], limit=1)
        if not tax_exempt:
            tax_exempt = self.env['account.tax'].create({
                'name': 'IVA Isento (M01)',
                'amount': 0.0,
                'type_tax_use': 'sale',
                'company_id': self.company_data['company'].id,
                'l10n_pt_tax_exemption_reason': 'M01',
            })
        else:
            tax_exempt.write({'l10n_pt_tax_exemption_reason': 'M01'})

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_pt.id,
            'invoice_date': '2026-01-15',
            'date': '2026-01-15',
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': prod_a.id,
                    'quantity': 1,
                    'price_unit': 100.0,
                    'tax_ids': [(6, 0, self.tax_sale_23.ids)],
                }),
                (0, 0, {
                    'product_id': prod_b.id,
                    'quantity': 2,
                    'price_unit': 50.0,
                    'tax_ids': [(6, 0, tax_exempt.ids)],
                }),
            ],
        })
        invoice.action_post()

        # 3. Create credit note referencing invoice
        credit_note = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.partner_pt.id,
            'invoice_date': '2026-01-18',
            'date': '2026-01-18',
            'reversed_entry_id': invoice.id,
            'ref': f'Reversal of {invoice.name}',
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': prod_b.id,
                    'quantity': 1,
                    'price_unit': 50.0,
                    'tax_ids': [(6, 0, tax_exempt.ids)],
                }),
            ],
        })
        credit_note.action_post()

        # 4. Create invoice with foreign partner
        inv_foreign = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_es.id,
            'invoice_date': '2026-01-20',
            'date': '2026-01-20',
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': prod_a.id,
                    'quantity': 5,
                    'price_unit': 80.0,
                    'tax_ids': [(6, 0, tax_exempt.ids)],
                }),
            ],
        })
        inv_foreign.action_post()

        # 5. Run SAF-T Export Wizard with mocked producer credentials
        with self._mock_sign_records(), \
             patch.object(wizard_module, 'PT_PRODUCER_VAT', '599999993'), \
             patch.object(wizard_module, 'PT_CERTIFICATION_NUMBER', '1234'):
            wizard = self.env['l10n_pt.saft.export.wizard'].create({
                'company_id': self.company_data['company'].id,
                'date_from': '2026-01-01',
                'date_to': '2026-01-31',
                'type': 'F',
            })
            wizard.action_export_saft()

            self.assertTrue(wizard.export_file, "SAF-T file binary must be generated.")
            xml_content = base64.b64decode(wizard.export_file)
            root = ET.fromstring(xml_content)

            # Check Header
            header = root.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Header')
            self.assertIsNotNone(header)
            self.assertEqual(header.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}AuditFileVersion').text, '1.04_01')
            self.assertEqual(header.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}ProductCompanyTaxID').text, '599999993')
            self.assertEqual(header.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}SoftwareCertificateNumber').text, '1234')
            self.assertEqual(header.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}ProductID').text, PT_PRODUCT_ID)

            # Check MasterFiles - Customers
            customers = root.findall('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Customer')
            pt_cust = next((c for c in customers if c.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CustomerID').text == str(self.partner_pt.id)), None)
            self.assertIsNotNone(pt_cust)
            # Domestic PT VAT stripped of 'PT' prefix
            self.assertEqual(pt_cust.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CustomerTaxID').text, '501234560')

            es_cust = next((c for c in customers if c.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CustomerID').text == str(self.partner_es.id)), None)
            self.assertIsNotNone(es_cust)
            # Foreign ES VAT retains prefix
            self.assertEqual(es_cust.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CustomerTaxID').text, 'ESA12345674')

            # Check MasterFiles - Products (Unique ProductCode)
            products = root.findall('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Product')
            product_codes = [p.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}ProductCode').text for p in products]
            self.assertEqual(len(product_codes), len(set(product_codes)), "All ProductCodes must be strictly unique.")

            # Check SourceDocuments - SalesInvoices Lines and TaxCodes
            lines = root.findall('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Line')
            for line in lines:
                reason = line.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}TaxExemptionReason')
                if reason is not None and reason.text:
                    self.assertLessEqual(len(reason.text), 60, f"TaxExemptionReason '{reason.text}' exceeds 60 characters.")
                tax_code = line.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}TaxCode')
                self.assertIsNotNone(tax_code, "Line TaxCode element must be present.")
                self.assertIn(tax_code.text, ('RED', 'INT', 'NOR', 'ISE', 'OUT'))

            # Check Credit Note References
            cn_elem = next(
                inv for inv in root.findall('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Invoice')
                if inv.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}InvoiceType').text == 'NC'
            )
            self.assertIsNotNone(cn_elem)
            cn_lines = cn_elem.findall('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Line')
            for cl in cn_lines:
                ref = cl.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}References')
                self.assertIsNotNone(ref, "Credit note line must have <References> element.")
                self.assertTrue(ref.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Reference').text)

            # Validate with official schema if xmlschema is present
            schema_path = os.path.join(os.path.dirname(__file__), 'data', 'SAF-T_PT_1.04_01.xsd')
            if not xmlschema:
                self.skipTest("xmlschema library is not installed")
            if not os.path.exists(schema_path):
                self.skipTest(f"SAF-T XSD schema not found at {schema_path}")
            schema = xmlschema.XMLSchema11(schema_path)
            self.assertTrue(schema.is_valid(xml_content), f"SAF-T XML validation failed: {schema.validate(xml_content)}")

    def test_saft_address_validation(self):
        """Test customer missing address succeeds with 'Desconhecido', while company missing address raises UserError."""
        # 1. Customer with missing street succeeds and exports 'Desconhecido'
        incomplete_partner = self.env['res.partner'].create({
            'name': 'Cliente Sem Rua',
            'street': False,  # Missing street
            'city': 'Porto',
            'zip': '4000-001',
            'country_id': self.env.ref('base.pt').id,
        })
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': incomplete_partner.id,
            'invoice_date': '2026-01-25',
            'date': '2026-01-25',
            'invoice_line_ids': [
                (0, 0, {
                    'name': 'Item',
                    'quantity': 1,
                    'price_unit': 10.0,
                    'tax_ids': [(6, 0, self.tax_sale_23.ids)],
                }),
            ],
        })
        invoice.action_post()

        with self._mock_sign_records(), \
             patch.object(wizard_module, 'PT_PRODUCER_VAT', '599999993'), \
             patch.object(wizard_module, 'PT_CERTIFICATION_NUMBER', '1234'):
            wizard = self.env['l10n_pt.saft.export.wizard'].create({
                'company_id': self.company_data['company'].id,
                'date_from': '2026-01-01',
                'date_to': '2026-01-31',
                'type': 'F',
            })
            wizard.action_export_saft()
            self.assertTrue(wizard.export_file, "Export should succeed when customer address is incomplete")
            xml_content = base64.b64decode(wizard.export_file)
            root = ET.fromstring(xml_content)
            cust_elem = next(
                c for c in root.findall('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Customer')
                if c.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CustomerID').text == str(incomplete_partner.id)
            )
            self.assertEqual(cust_elem.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}AddressDetail').text, 'Desconhecido')

            # 2. Company with missing address raises UserError
            self.company_data['company'].street = False
            with self.assertRaises(UserError) as cm:
                wizard.action_export_saft()
            self.assertIn("address", str(cm.exception).lower())

    def test_saft_payments_validation(self):
        """Test payment receipts in SAF-T export: partial payment reconciled with invoice and canceled receipt."""
        with self._mock_sign_records(), \
             patch.object(wizard_module, 'PT_PRODUCER_VAT', '599999993'), \
             patch.object(wizard_module, 'PT_CERTIFICATION_NUMBER', '1234'):
            invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.partner_pt.id,
                'invoice_date': '2026-01-10',
                'date': '2026-01-10',
                'invoice_line_ids': [
                    (0, 0, {
                        'name': 'Serviço de Consultoria',
                        'quantity': 1,
                        'price_unit': 100.0,
                        'tax_ids': [(6, 0, self.tax_sale_23.ids)],
                    }),
                ],
            })
            invoice.action_post()

            # 1. Partial payment (50.00 EUR) reconciled with invoice
            payment_register = self.env['account.payment.register'].with_company(self.company_data['company']).with_context(
                active_model='account.move', active_ids=invoice.ids
            ).create({
                'journal_id': self.company_data['default_journal_bank'].id,
                'amount': 50.0,
                'payment_date': '2026-01-12',
            })
            payment_res = payment_register.action_create_payments()
            payment_partial = self.env['account.payment'].browse(payment_res['res_id']) if 'res_id' in payment_res else self.env['account.payment'].search([
                ('company_id', '=', self.company_data['company'].id),
                ('payment_type', '=', 'inbound'),
                ('partner_id', '=', self.partner_pt.id),
            ], order='id desc', limit=1)

            # 2. Canceled payment settling invoice2
            invoice2 = self.env['account.move'].with_company(self.company_data['company']).create({
                'move_type': 'out_invoice',
                'partner_id': self.partner_pt.id,
                'invoice_date': '2026-01-14',
                'invoice_line_ids': [
                    Command.create({
                        'name': 'Test Service 2',
                        'quantity': 1.0,
                        'price_unit': 20.0,
                        'tax_ids': [Command.set(self.tax_sale_23.ids)],
                    })
                ]
            })
            invoice2.action_post()
            self.env['account.move']._l10n_pt_compute_missing_hashes()

            payment_reg2 = self.env['account.payment.register'].with_company(self.company_data['company']).with_context(
                active_model='account.move', active_ids=invoice2.ids
            ).create({
                'journal_id': self.company_data['default_journal_bank'].id,
                'amount': invoice2.amount_total,
                'payment_date': '2026-01-15',
            })
            payment_res2 = payment_reg2.action_create_payments()
            payment_canceled = self.env['account.payment'].browse(payment_res2['res_id']) if 'res_id' in payment_res2 else self.env['account.payment'].search([
                ('company_id', '=', self.company_data['company'].id),
                ('payment_type', '=', 'inbound'),
                ('partner_id', '=', self.partner_pt.id),
            ], order='id desc', limit=1)
            payment_canceled.action_cancel()

            wizard = self.env['l10n_pt.saft.export.wizard'].create({
                'company_id': self.company_data['company'].id,
                'date_from': '2026-01-01',
                'date_to': '2026-01-31',
                'type': 'F',
            })
            wizard.action_export_saft()
            self.assertTrue(wizard.export_file, "SAF-T file binary must be generated.")
            xml_content = base64.b64decode(wizard.export_file)
            root = ET.fromstring(xml_content)

            payments_elem = root.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Payments')
            self.assertIsNotNone(payments_elem, "Payments element must exist in SAF-T export.")
            self.assertEqual(payments_elem.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}NumberOfEntries').text, '2')
            self.assertEqual(payments_elem.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}TotalDebit').text, '0.00')
            self.assertEqual(payments_elem.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}TotalCredit').text, '50.00')

            payment_nodes = payments_elem.findall('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Payment')
            self.assertEqual(len(payment_nodes), 2)

            # Check active partial payment
            node_partial = next(p for p in payment_nodes if p.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}PaymentRefNo').text == payment_partial.l10n_pt_document_number)
            self.assertEqual(node_partial.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}PaymentStatus').text, 'N')
            pmt_method = node_partial.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}PaymentMethod')
            self.assertIsNotNone(pmt_method)
            self.assertEqual(pmt_method.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}PaymentAmount').text, '50.00')
            line_elem = node_partial.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Line')
            self.assertEqual(line_elem.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}OriginatingON').text, invoice.l10n_pt_document_number)
            self.assertEqual(line_elem.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CreditAmount').text, '50.00')

            # Check canceled payment preserves settled invoice
            node_canceled = next(p for p in payment_nodes if p.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}PaymentRefNo').text == payment_canceled.l10n_pt_document_number)
            self.assertEqual(node_canceled.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}PaymentStatus').text, 'A')
            line_canc = node_canceled.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}Line')
            self.assertEqual(line_canc.find('.//{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}OriginatingON').text, invoice2.l10n_pt_document_number)
            self.assertEqual(line_canc.find('{urn:OECD:StandardAuditFile-Tax:PT_1.04_01}CreditAmount').text, float_repr(invoice2.amount_total, 2))

            # Schema validation
            schema_path = os.path.join(os.path.dirname(__file__), 'data', 'SAF-T_PT_1.04_01.xsd')
            if xmlschema and os.path.exists(schema_path):
                schema = xmlschema.XMLSchema11(schema_path)
                self.assertTrue(schema.is_valid(xml_content), f"SAF-T Payments validation failed: {schema.validate(xml_content)}")

    def test_saft_payments_unreconciled_refused(self):
        """Test that unreconciled payments (advances without invoice) are refused per Art. 29.º n.º 1 c) CIVA."""
        unreconciled_pmt = self.env['account.payment'].with_company(self.company_data['company']).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_pt.id,
            'amount': 30.0,
            'date': '2026-01-16',
            'journal_id': self.company_data['default_journal_bank'].id,
        })
        unreconciled_pmt.action_post()
        from odoo.addons.l10n_pt_certification.wizard import l10n_pt_saft_export_wizard as wm
        with self._mock_sign_records(), \
             patch.object(wm, 'PT_PRODUCER_VAT', '599999993'), \
             patch.object(wm, 'PT_CERTIFICATION_NUMBER', '1234'):
            wizard = self.env['l10n_pt.saft.export.wizard'].create({
                'company_id': self.company_data['company'].id,
                'date_from': '2026-01-01',
                'date_to': '2026-01-31',
                'type': 'F',
            })
            with self.assertRaises(UserError):
                wizard.action_export_saft()

    def test_pt_receipt_unreconcile_blocked(self):
        """Test that unreconciling an active PT payment receipt is blocked."""
        inv = self.env['account.move'].with_company(self.company_data['company']).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_pt.id,
            'invoice_date': '2026-01-20',
            'invoice_line_ids': [
                Command.create({
                    'name': 'Serviço Teste',
                    'quantity': 1.0,
                    'price_unit': 100.0,
                    'tax_ids': [Command.set(self.tax_sale_23.ids)],
                })
            ]
        })
        inv.action_post()
        payment_reg = self.env['account.payment.register'].with_company(self.company_data['company']).with_context(
            active_model='account.move', active_ids=inv.ids
        ).create({
            'journal_id': self.company_data['default_journal_bank'].id,
            'amount': inv.amount_total,
            'payment_date': '2026-01-21',
        })
        res = payment_reg.action_create_payments()
        pmt = self.env['account.payment'].browse(res['res_id'])
        self.assertTrue(pmt.l10n_pt_settled_documents)

        # Attempting to unreconcile an active receipt must raise UserError
        with self.assertRaises(UserError):
            (inv.line_ids + pmt.move_id.line_ids).remove_move_reconcile()

