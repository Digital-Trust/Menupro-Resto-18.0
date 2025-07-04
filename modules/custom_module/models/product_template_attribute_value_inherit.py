import requests
from odoo import models, api, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    menuproId = fields.Char(string="MenuPro ID", copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info("Création product.template.attribute.value: %s", vals_list)
        res = super().create(vals_list)
        restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
        if not restaurant_id:
            raise UserError("Le paramètre restaurant_id est manquant dans la config.")

        for record in res:
            try:
                payload = {
                    "odoo_id": record.id,
                    "odoo_product_tmpl_id": record.product_tmpl_id.id,
                    "odoo_attribute_id": record.attribute_id.id,
                    "odoo_attribute_line_id": record.attribute_line_id.id,
                    "odoo_attribute_value_id": record.product_attribute_value_id.id,
                    "price_extra": record.price_extra,
                    "html_color": record.html_color or "",
                    "is_custom": record.is_custom,
                    "display_type": record.display_type,
                    "ptav_active": record.ptav_active,
                    "restaurant_id": restaurant_id,
                }

                response = requests.post(
                    "http://localhost:3000/attributs/template-attribute/values",
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                record.menuproId = data.get('_id')
                _logger.info(f"Sync réussie product.template.attribute.value {record.id}")
            except Exception as e:
                _logger.warning(f"Erreur sync template attribute value {record.id}: {e}")

        return res
