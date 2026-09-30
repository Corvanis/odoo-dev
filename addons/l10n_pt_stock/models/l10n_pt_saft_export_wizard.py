# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class L10nPtSaftExportWizard(models.TransientModel):
    _inherit = "l10n_pt.saft.export.wizard"

    def _get_movement_documents(self, company):
        start_dt = fields.Datetime.to_datetime(self.date_from)
        end_dt = fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59, second=59)
        return self.env['stock.picking'].search([
            ('company_id', '=', company.id),
            ('l10n_pt_document_number', '!=', False),
            ('state', 'in', ('done', 'cancel')),
            '|',
            '&', ('date_done', '>=', start_dt), ('date_done', '<=', end_dt),
            '&', ('date_done', '=', False), '&', ('l10n_pt_start_transport_date', '>=', start_dt), ('l10n_pt_start_transport_date', '<=', end_dt),
        ], order='l10n_pt_sequence_number, id')
