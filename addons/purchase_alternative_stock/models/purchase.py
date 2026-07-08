# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    on_time_rate_perc = fields.Float(string="OTD", compute="_compute_on_time_rate_perc")

    @api.depends('on_time_rate')
    def _compute_on_time_rate_perc(self):
        for po in self:
            if po.on_time_rate >= 0:
                po.on_time_rate_perc = po.on_time_rate / 100
            else:
                po.on_time_rate_perc = -1


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    on_time_rate_perc = fields.Float(string="OTD", related="order_id.on_time_rate_perc")

    def _get_countable_rfq_groups(self, groups):
        groups = list(super()._get_countable_rfq_groups(groups))
        qty_by_order = {}
        for order, product, *_, qty in groups:
            if purchase_group := order.purchase_group_id:
                key = purchase_group.id, product.id
                order_qty = qty_by_order.setdefault(key, {})
                order_qty[order.id] = order_qty.get(order.id, 0.0) + qty

        countable_orders = {
            key: max(order_qty, key=order_qty.get)
            for key, order_qty in qty_by_order.items()
        }
        return [
            group for group in groups
            if not (purchase_group := group[0].purchase_group_id)
            or group[0].id == countable_orders[purchase_group.id, group[1].id]
        ]
