from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_pt_certification.models.l10n_pt_at_series import AT_SERIES_ACCOUNTING_DOCUMENT_TYPES


class AccountPayment(models.Model):
    _name = 'account.payment'
    _inherit = ['account.payment', 'l10n.pt.document.mixin']

    _l10n_pt_document_type_depends = ('country_code', 'payment_type')

    l10n_pt_at_series_id = fields.Many2one(
        compute='_compute_l10n_pt_at_series_id',
        readonly=False, store=True,
        domain="[('journal_id', '=', journal_id)]",
    )
    l10n_pt_document_type = fields.Selection(selection_add=AT_SERIES_ACCOUNTING_DOCUMENT_TYPES)
    l10n_pt_settled_documents = fields.Json(
        string="Settled Documents",
        copy=False,
        readonly=True,
        help="Details of invoices settled by this payment (document number, date, amount).",
    )

    def is_pt_inbound(self):
        return self.country_code == 'PT' and self.payment_type == 'inbound'

    def _l10n_pt_country_ok(self):
        self.ensure_one()
        return self.is_pt_inbound()

    def _l10n_pt_get_document_date(self):
        self.ensure_one()
        return self.date

    def _l10n_pt_get_document_type(self):
        self.ensure_one()
        return 'payment_receipt'

    def _l10n_pt_get_settled_documents(self):
        """
        Return the list of documents settled by this payment.
        Each item has {'document_number', 'date', 'amount', 'description'}.
        If already stored (e.g. before cancellation or previously snapshotted), return stored data.
        Otherwise, compute dynamically from reconciled invoices.
        """
        self.ensure_one()
        if self.state == 'canceled' and self.l10n_pt_settled_documents:
            return self.l10n_pt_settled_documents

        invoice_partials, _unused = self.move_id._get_reconciled_invoices_partials()
        inv_amounts = {}
        for partial, _amt_curr, counterpart_line in invoice_partials:
            inv = counterpart_line.move_id
            if inv.is_sale_document(include_receipts=True):
                inv_amounts[inv] = inv_amounts.get(inv, 0.0) + abs(partial.amount)

        if not inv_amounts and self.l10n_pt_settled_documents:
            return self.l10n_pt_settled_documents

        settled = []
        for inv, amt in inv_amounts.items():
            doc_no = inv.l10n_pt_document_number or inv.name
            inv_date = (inv.invoice_date or self.date).strftime('%Y-%m-%d')
            settled.append({
                'document_number': doc_no,
                'date': inv_date,
                'amount': amt,
                'description': doc_no,
            })
        return settled

    ####################################
    # OVERRIDES
    ####################################

    def action_post(self):
        pt_payments = self.filtered(lambda p: p.is_pt_inbound()).sorted('date')
        pt_payments._check_l10n_pt_dates()
        pt_payments._set_l10n_pt_document_number()
        res = super().action_post()
        for payment in pt_payments:
            settled = payment._l10n_pt_get_settled_documents()
            if settled:
                payment.l10n_pt_settled_documents = settled
        return res

    def action_cancel(self):
        for payment in self.filtered(lambda p: p.is_pt_inbound() and not p.l10n_pt_settled_documents):
            settled = payment._l10n_pt_get_settled_documents()
            if settled:
                payment.l10n_pt_settled_documents = settled
        res = super().action_cancel()
        pt_payments = self.filtered(lambda p: p.is_pt_inbound() and not p.l10n_pt_cancelled_on)
        if pt_payments:
            pt_payments.write({'l10n_pt_cancelled_on': fields.Datetime.now()})
        return res

    def write(self, vals):
        if (
            'l10n_pt_at_series_id' in vals
            and self.filtered(lambda p: p.country_code == 'PT' and p.state in ('in_process', 'paid', 'canceled'))
        ):
            raise UserError(_("The AT Series of a payment being processed, paid or canceled cannot be changed."))
        return super().write(vals)

    def action_open_reprint_wizard(self):
        """ PT requirement: documents being reprinted require a reprint reason """
        if self.filtered(lambda p: p.country_code == 'PT' and p.l10n_pt_print_version):
            return self.env.ref('l10n_pt_certification.action_open_reprint_wizard').read()[0]
        return self.env.ref('account.action_report_payment_receipt').report_action(self)

    ####################################
    # MISC REQUIREMENTS
    ####################################

    ####################################
    # PT FIELDS - ATCUD, AT SERIES
    ####################################

    @api.depends('payment_type', 'company_id', 'date', 'journal_id')
    def _compute_l10n_pt_at_series_id(self):
        payments = self.filtered(
            lambda p: not p.l10n_pt_at_series_id
            or p.l10n_pt_at_series_id.journal_id != p.journal_id
            or not p.l10n_pt_at_series_id._l10n_pt_is_valid_on(fields.Date.to_date(p._l10n_pt_get_document_date()))
        )
        at_series_model = self.env['l10n_pt.at.series']
        for payment in payments:
            doc_date = fields.Date.to_date(payment._l10n_pt_get_document_date())
            last_payment = self.env['account.payment'].search([
                ('company_id', '=', payment.company_id.id),
                ('payment_type', '=', 'inbound'),
                ('journal_id', '=', payment.journal_id.id),
                ('l10n_pt_document_type', '=', 'payment_receipt'),
                ('l10n_pt_at_series_id', '!=', False),
                *at_series_model._l10n_pt_validity_domain(
                    doc_date, prefix='l10n_pt_at_series_id.',
                ),
            ], order='id desc', limit=1)
            at_series = last_payment.l10n_pt_at_series_id or at_series_model.with_context(active_test=False).search([
                *at_series_model._l10n_pt_company_domain(payment.company_id),
                ('document_type', '=', 'payment_receipt'),
                ('journal_id', '=', payment.journal_id.id),
                *at_series_model._l10n_pt_validity_domain(doc_date),
            ], limit=1)
            payment.l10n_pt_at_series_id = at_series

    @api.constrains('l10n_pt_at_series_id')
    def _check_l10n_pt_at_series_id(self):
        super()._check_l10n_pt_at_series_id()
