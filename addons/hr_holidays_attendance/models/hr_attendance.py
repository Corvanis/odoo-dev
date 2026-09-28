# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models

# fields that when changed invalidate previously credited allocations
_TIME_FIELDS = frozenset({'check_in', 'check_out', 'employee_id'})

# states in which an attendance no longer counts as valid source material
_INVALID_STATES = frozenset({'refused', 'draft'})


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    work_entry_type_id = fields.Many2one(
        domain="[('id', 'in', allowed_work_entry_type_ids), ('count_as', '=', 'working_time'), ('requires_allocation', '=', False)]",
    )

    def write(self, vals):
        to_reverse = set()
        if not self.env.context.get('skip_time_rules') and _TIME_FIELDS & vals.keys():
            to_reverse.update(self.ids)
        if vals.get('state') in _INVALID_STATES:
            to_reverse.update(self.filtered(lambda a: a.state == 'validated').ids)
        if to_reverse:
            self.env['hr.time.rule']._reverse_allocation_credits('hr.attendance', to_reverse)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _reverse_credits_on_unlink(self):
        self.env['hr.time.rule']._reverse_allocation_credits('hr.attendance', self.ids)
