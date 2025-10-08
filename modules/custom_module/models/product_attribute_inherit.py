from odoo import models, fields, api, tools
import requests
import logging

from odoo.exceptions import UserError
from odoo.http import request
from ..utils.security_utils import mask_sensitive_data

_logger = logging.getLogger(__name__)

class ProductAttribute(models.Model):
    _inherit = 'product.attribute'
    menuproId = fields.Char(string="MenuPro ID", copy=False)

    def _get_config(self):
        """Charge et valide la config une seule fois par thread."""
        if hasattr(self.env, "_mp_config"):
            return self.env._mp_config

        ICParam = self.env['ir.config_parameter'].sudo()

        cfg = {
            'attributs_url': tools.config.get('attributs_url'),
            'secret_key': tools.config.get('secret_key'),
            'odoo_secret_key': tools.config.get('odoo_secret_key'),
            'restaurant_id': ICParam.get_param('restaurant_id'),
        }

        for k, v in cfg.items():
            if not v:
                _logger.error("%s is missing in config", k)
                raise UserError(f"L’option '{k}' est manquante dans la configuration.")

        self.env._mp_config = cfg
        masked_cfg = mask_sensitive_data(cfg)
        _logger.info("\033[92mMenuPro config OK: %s\033[0m", masked_cfg)
        return cfg

    def _build_payload(self):
        cfg = self._get_config()
        self.ensure_one()
        return {
            "odoo_id": self.id,
            "menuProName": self.name,
            "create_variant": self.create_variant,
            "display_type": self.display_type,
            "sequence": self.sequence,
            "status": "active" if self.active else "archived",
            "active": self.active,
            "restaurant_id": cfg['restaurant_id'],
            "values": [
                {
                    "odoo_id": v.id,
                    "menuProName": v.name,
                    "sequence": v.sequence,
                    "html_color": v.html_color or "",
                    "is_custom": v.is_custom,
                    "status": "active" if v.active else "archived",
                    "active": v.active,
                    "default_extra_price": v.default_extra_price,
                    "restaurant_id": cfg['restaurant_id'],
                }
                for v in self.value_ids            ],

        }

    def _call_mp(self, method, url, json=None):
        cfg = self._get_config()
        headers = {
            "x-secret-key": cfg['secret_key'],
            "x-odoo-secret-key": cfg['odoo_secret_key'],
        }
        try:
            resp = requests.request(method, url, json=json, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except Exception as e:
            _logger.warning("MenuPro %s %s failed → %s", method, url, e)
            raise

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        cfg = self._get_config()
        base = cfg['attributs_url']

        for rec in records:
            data = rec._call_mp("POST", base, rec._build_payload())
            rec.menuproId = data.get("_id")

            # map des valeurs
            vmap = {v["odoo_id"]: v["_id"] for v in data.get("values", [])}
            for val in rec.value_ids:
                val.menuproId = vmap.get(val.id)
        return records

    def write(self, vals):
        res = super().write(vals)
        cfg = self._get_config()
        base = cfg['attributs_url']

        for rec in self:
            payload = rec._build_payload()

            if not rec.menuproId:
                response = rec._call_mp("POST", base, payload)
                rec.menuproId = response.get("_id")
            else:
                response = rec._call_mp("PATCH", f"{base}/{rec.menuproId}", payload)

            # On map les valeurs si la réponse contient des values
            if response and "values" in response:
                vmap = {v["odoo_id"]: v["_id"] for v in response["values"]}
                for val in rec.value_ids:
                    if not val.menuproId and val.id in vmap:
                        val.menuproId = vmap[val.id]
                        _logger.info("🆕 Attribution du MenuPro ID à val.id=%s → %s", val.id, vmap[val.id])
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used_on_product(self):
        cfg = self._get_config()
        base = cfg['attributs_url']
        res = super()._unlink_except_used_on_product()
        for rec in self:
            if rec.menuproId:
                rec._call_mp("DELETE", f"{base}/{rec.menuproId}")
        return res