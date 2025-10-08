from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    menuproId = fields.Char(string="MenuPro ID", copy=False)

    def _get_config(self):
        return self.env['product.attribute']._get_config()

    def _call_mp(self, method, url, json=None):
        return self.env['product.attribute']._call_mp(method, url, json)

    def _build_payload(self):
        self.ensure_one()
        cfg = self._get_config()
        payload = {
            "odoo_id": self.id,
            "odoo_attribute_line_id": self.attribute_line_id.id,
            "odoo_product_attribute_value_id": self.product_attribute_value_id.id,
            "menupro_product_attribute_value_id": self.product_attribute_value_id.menuproId,
            "odoo_product_tmpl_id": self.product_tmpl_id.id,
            "odoo_attribute_id": self.attribute_id.id,
            "menupro_attribute_id": self.attribute_id.menuproId,
            "ptav_active": self.ptav_active,
            "price_extra": self.price_extra,
            "restaurant_id": cfg["restaurant_id"],
        }
        if self.product_tmpl_id.menupro_id:
            payload["menupro_tmpl_id"] = self.product_tmpl_id.menupro_id

        return payload

    @api.model_create_multi
    def create(self, vals_list):
        _logger.debug("Creating ProductTemplateAttributeValue with vals: %s", vals_list)
        records = super().create(vals_list)
        _logger.debug("Created ProductTemplateAttributeValue records: %s", records)

        cfg = self._get_config()
        base = f"{cfg['attributs_url']}/template-values"

        for rec in records:
            try:


                payload = rec._build_payload()
                _logger.debug("PTAV Payload to send: %s", payload)
                
                data = rec._call_mp("POST", base, payload)
                _logger.debug("PTAV Response received: %s", data)

                if data and data.get("_id"):
                    rec.menuproId = data.get("_id")

            except Exception as e:
                _logger.error(f"Erreur lors de la création de la valeur template: {e}")

        return records

    def write(self, vals):
        res = super().write(vals)
        cfg = self._get_config()
        base = f"{cfg['attributs_url']}/template-values"

        for rec in self:
            try:
                payload = rec._build_payload()

                if rec.menuproId:
                    rec._call_mp("PATCH", f"{base}/{rec.menuproId}", payload)
                else:
                    response = rec._call_mp("POST", base, payload)
                    rec.menuproId = response.get("_id")

            except Exception as e:
                _logger.error(f"Erreur lors de la sync de la valeur template: {e}")

        return res

    def unlink(self):
        cfg = self._get_config()
        base = f"{cfg['attributs_url']}/template-values"

        for rec in self:
            if rec.menuproId:
                try:
                    rec._call_mp("DELETE", f"{base}/{rec.menuproId}")
                except Exception as e:
                    _logger.error(f"Erreur lors de la suppression de la valeur template: {e}")

        return super().unlink()