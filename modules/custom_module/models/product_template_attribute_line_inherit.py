import requests

from odoo import api, models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'

    menuproId = fields.Char(string="MenuPro ID", copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)

        restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
        if not restaurant_id:
            raise UserError("Il manque le restaurant_id dans la configuration")

        for rec in res:
            try:
                payload = {
                    "odoo_id": rec.id,
                    "product_tmpl_id": rec.product_tmpl_id.id,
                    "odoo_product_tmpl_id": rec.product_tmpl_id.id,
                    "odoo_attribute_id": rec.attribute_id.id,
                    "sequence": rec.sequence,
                    "active": rec.active,
                    "odoo_selected_value_ids": rec.value_ids.ids,
                    "restaurant_id": restaurant_id,
                }
                import requests
                response = requests.post(
                    "http://localhost:3000/attributs/template-attribute-lines",
                    json=payload,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                rec.menuproId = data.get('_id')
            except Exception as e:
                _logger.warning(f"Erreur sync template attribute line {rec.id}: {e}")

        return res


