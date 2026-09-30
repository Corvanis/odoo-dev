from odoo import _, api, models
from odoo.exceptions import UserError


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        payments = (
            partials.debit_move_id.payment_id | partials.debit_move_id.move_id.origin_payment_id |
            partials.credit_move_id.payment_id | partials.credit_move_id.move_id.origin_payment_id
        ).filtered(lambda p: p.is_pt_inbound() and not p.l10n_pt_settled_documents)
        for pmt in payments:
            settled = pmt._l10n_pt_get_settled_documents()
            if settled:
                pmt.l10n_pt_settled_documents = settled
        return partials

    def unlink(self):
        for partial in self:
            payments = (
                partial.debit_move_id.payment_id | partial.debit_move_id.move_id.origin_payment_id |
                partial.credit_move_id.payment_id | partial.credit_move_id.move_id.origin_payment_id
            ).filtered(
                lambda p: p.is_pt_inbound() and p.l10n_pt_settled_documents and p.state != 'canceled'
            )
            if payments:
                raise UserError(_(
                    "You cannot unreconcile a Portuguese certified payment receipt (%s) that has already settled invoices. "
                    "Cancel the payment receipt instead.",
                    ", ".join(payments.mapped('l10n_pt_document_number') or payments.mapped('name'))
                ))
        return super().unlink()
