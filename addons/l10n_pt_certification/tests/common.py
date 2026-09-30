import base64
import datetime
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from freezegun import freeze_time

from odoo import Command, fields
from odoo.models import Model

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestL10nPtCommon(AccountTestInvoicingCommon):
    @classmethod
    @AccountTestInvoicingCommon.setup_country('pt')
    def setUpClass(cls):
        def create_at_series(year):
            sale_journal = cls.company_data['default_journal_sale']
            bank_journal = cls.company_data['default_journal_bank']
            series = cls.env['l10n_pt.at.series'].create([{
                'name': year,
                'company_id': cls.company_pt.id,
                'training_series': True,
                'company_exclusive_series': True,
                'date_start': f"{year}-01-01",
                'date_end': f"{year}-12-31",
                'journal_id': bank_journal.id if series_type == 'payment_receipt' else sale_journal.id,
                'document_type': series_type,
                'prefix': prefix,
                'at_code': f'AT-TEST{prefix}{year}',
            } for series_type, prefix in (('out_invoice', 'FT'), ('out_receipt', 'FS'), ('out_refund', 'RINV'), ('payment_receipt', 'PAY'))])
            return series

        super().setUpClass()
        cls.company_pt = cls.company_data['company']
        cls.company_pt.write({
            'street': '25 Avenida da Liberdade',
            'city': 'Lisboa',
            'zip': '9415-343',
            'company_registry': '123456',
            'phone': '+351 11 11 11 11',
            'country_id': cls.env.ref('base.pt').id,
            'account_fiscal_country_id': cls.env.ref('base.pt').id,
            'vat': 'PT123456789',
        })
        cls.partner_a.vat = 'PT123456789'
        cls.company_data_2 = cls.setup_other_company()
        cls.series_2017 = create_at_series('2017')
        cls.series_2024 = create_at_series('2024')
        cls.series_2026 = create_at_series('2026')
        cls.tax_sale_23 = cls.env['account.chart.template'].ref('iva_pt_sale_normal')
        cls.tax_sale_0 = cls.env['account.chart.template'].ref('iva_pt_sale_eu_isenta')
        cls._test_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls._test_public_key_pem = cls._test_private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode('utf-8')
        cls.at_public_cert = cls.env['certificate.certificate'].create({
            'name': 'AT Public Cert Test',
            'content': cls._get_test_rsa_public_key_pem_b64(cls._test_private_key),
            'company_id': cls.company_pt.id,
        })
        cls.company_pt.l10n_pt_at_ws_public_cert_id = cls.at_public_cert

    @staticmethod
    def _get_test_rsa_public_key_pem_b64(key=None):
        if key is None:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(x509.oid.NameOID.COUNTRY_NAME, "PT"),
            x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, "Autoridade Tributaria"),
            x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "at.gov.pt"),
        ])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            now - datetime.timedelta(days=10)
        ).not_valid_after(
            now + datetime.timedelta(days=365)
        ).sign(key, hashes.SHA256())
        return base64.b64encode(cert.public_bytes(serialization.Encoding.PEM))

    @classmethod
    def create_invoice(cls, move_type='out_invoice', invoice_date='2024-01-01', post=True, l10n_pt_hashed_on=None, amount=1000.0,
                       quantity=1, tax=None, product_id=False, do_hash=False, mock_hash=False, reversed_entry_id=False, ref=False):
        invoice_data = {
            'company_id': cls.company_pt.id,
            'move_type': move_type,
            'partner_id': cls.partner_a.id,
            'invoice_date': fields.Date.from_string(invoice_date),
            'line_ids': [
                Command.create({
                    'name': 'Product A',
                    'product_id': product_id,
                    'quantity': quantity,
                    'price_unit': amount,
                    'tax_ids': [tax.id if tax else cls.tax_sale_23.id],
                }),
            ],
        }
        if reversed_entry_id:
            invoice_data['reversed_entry_id'] = reversed_entry_id
        if ref:
            invoice_data['ref'] = ref
        elif move_type == 'out_refund' and post and not reversed_entry_id:
            invoice_data['ref'] = 'REF-ORIGINAL-INVOICE'

        year = str(invoice_data['invoice_date'].year)
        if year == '2017':
            series_for_year = cls.series_2017
        elif year == '2026':
            series_for_year = cls.series_2026
        else:
            series_for_year = cls.series_2024
        invoice_data['l10n_pt_at_series_id'] = series_for_year.filtered(lambda s: s.document_type == move_type).id

        move = cls.env['account.move'].with_company(cls.company_pt).create(invoice_data)
        if post:
            move.action_post()
        if do_hash:
            if not l10n_pt_hashed_on:
                l10n_pt_hashed_on = fields.Date.today()
            if mock_hash:
                cls._inject_fake_hash(move)
            else:
                with freeze_time(l10n_pt_hashed_on), cls._mock_sign_records():
                    move.button_hash()
        return move

    @classmethod
    @contextmanager
    def _mock_ws(cls, return_code=None, side_effect=None):
        mock_client = MagicMock()
        mock_service = MagicMock()
        mock_client.bind.return_value = mock_service

        kwargs = {'return_value': return_code} if side_effect is None else {'side_effect': side_effect}

        with patch(
            'odoo.addons.base.models.res_company.ResCompany._get_zeep_client__',
            return_value=mock_client,
        ), patch(
            'odoo.addons.l10n_pt_certification.models.l10n_pt_at_series.L10nPtATSeries._registar_serie',
            **kwargs,
        ) as mock_reg:
            yield mock_reg

    @classmethod
    @contextmanager
    def _mock_sign_records(cls):
        def fake_sign(env, docs_to_sign, model):
            res = {}
            for d in docs_to_sign:
                message = f"{d['date']};{d['system_entry_date']};{d['name']};{d['gross_total']};{d.get('previous_signature') or ''}"
                sig = cls._test_private_key.sign(
                    message.encode('utf-8'),
                    padding.PKCS1v15(),
                    hashes.SHA1(),
                )
                sig_b64 = base64.b64encode(sig).decode('utf-8')
                res[env[model].browse(int(d['id']))] = f"$1${sig_b64}"
            return res

        def fake_get_public_keys(env):
            return {1: cls._test_public_key_pem}

        with patch('odoo.addons.l10n_pt_certification.utils.hashing.sign_records', fake_sign), \
             patch('odoo.addons.l10n_pt_certification.utils.hashing.get_public_keys', fake_get_public_keys):
            yield

    @classmethod
    def _inject_fake_hash(cls, move, hash_str=None):
        hash_str = hash_str or ('A' * 40)
        Model.write(move, {
            'inalterable_hash': f'$1${hash_str}',
            'l10n_pt_hashed_on': fields.Datetime.now(),
        })
        move.flush_recordset()
