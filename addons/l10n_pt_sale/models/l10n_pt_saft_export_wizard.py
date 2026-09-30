# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class L10nPtSaftExportWizard(models.TransientModel):
    _inherit = "l10n_pt.saft.export.wizard"

    def _get_working_documents(self, company):
        start_dt = fields.Datetime.to_datetime(self.date_from)
        end_dt = fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59, second=59)
        return self.env['sale.order'].search([
            ('company_id', '=', company.id),
            ('l10n_pt_document_number', '!=', False),
            ('date_order', '>=', start_dt),
            ('date_order', '<=', end_dt),
        ], order='date_order, id')
