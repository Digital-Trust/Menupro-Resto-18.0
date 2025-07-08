# Correction dans ProductTemplateAttributeLine
from odoo import models, fields, api, tools
import logging

_logger = logging.getLogger(__name__)


class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'

    menuproId = fields.Char(string="MenuPro ID", copy=False)

    def _get_config(self):
        return self.env['product.attribute']._get_config()

    def _call_mp(self, method, url, json=None):
        return self.env['product.attribute']._call_mp(method, url, json)

    def _build_payload(self):
        cfg = self._get_config()
        self.ensure_one()

        payload = {
            "odoo_id": self.id,
            "odoo_product_tmpl_id": self.product_tmpl_id.id,
            "odoo_attribute_id": self.attribute_id.id,
            "menupro_attribute_id": self.attribute_id.menuproId,
            "sequence": self.sequence,
            "status": "active" if self.active else "inactive",
            "active": self.active,
            "restaurant_id": cfg["restaurant_id"],
        }

        if self.product_tmpl_id.menupro_id:
            payload["menupro_tmpl_id"] = self.product_tmpl_id.menupro_id

        return payload

    @api.model_create_multi
    def create(self, vals_list):
        print("product template lines vals =>", vals_list)
        records = super().create(vals_list)
        print("records line ==>", records)
        cfg = self._get_config()
        base = f"{cfg['attributs_url']}/product-template-lines"

        for rec in records:
            try:
                payload = rec._build_payload()
                print("Payload envoyé pour lines :", payload)

                data = rec._call_mp("POST", base, payload)
                print("Réponse reçue pour lines:", data)

                if data and data.get("_id"):
                    rec.menuproId = data.get("_id")

            except Exception as e:
                _logger.error(f"Erreur lors de la création de la ligne d'attribut: {e}")

        return records

    def write(self, vals):
        res = super().write(vals)
        cfg = self._get_config()
        base = f"{cfg['attributs_url']}/product-template-lines"

        for rec in self:
            if not rec.menuproId:
                continue
            try:

                payload = rec._build_payload()
                response = rec._call_mp("PATCH", f"{base}/{rec.menuproId}", payload)

                if response and "values" in response:
                    vmap = {v["odoo_id"]: v["_id"] for v in response["values"]}
                    for ptav in rec.product_template_attribute_value_ids:
                        if not ptav.menuproId and ptav.id in vmap:
                            ptav.menuproId = vmap[ptav.id]

            except Exception as e:
                _logger.error(f"Erreur lors de la mise à jour de la ligne d'attribut: {e}")

        return res

    def unlink(self):
        cfg = self._get_config()
        base = f"{cfg['attributs_url']}/product-template-lines"
        for rec in self:
            if rec.menuproId:
                try:
                    rec._call_mp("DELETE", f"{base}/{rec.menuproId}")
                except Exception as e:
                    _logger.error(f"Erreur lors de la suppression de la ligne d'attribut: {e}")
        return super().unlink()