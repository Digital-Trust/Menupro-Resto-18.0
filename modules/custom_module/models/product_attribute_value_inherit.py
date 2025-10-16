from odoo import models, fields, api, tools
from odoo.exceptions import UserError
from odoo.http import request
import requests
import logging
from ..utils.security_utils import mask_sensitive_data
from ..utils.config_cache import ConfigCache

_logger = logging.getLogger(__name__)

class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'
    menuproId = fields.Char(string="MenuPro ID", copy=False)

    def _get_config(self):
        """Charge et valide la config avec cache."""
        config_keys = [
            'attributs_url',
            'secret_key',
            'odoo_secret_key',
            'restaurant_id'
        ]
        
        cfg = ConfigCache.get_config(self.env, config_keys)
        
        masked_cfg = mask_sensitive_data(cfg)
        _logger.debug("\033[92mMenuPro config loaded: %s\033[0m", masked_cfg)
        return cfg

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

    def write(self, vals):
        res = super().write(vals)
        cfg = self._get_config()

        for rec in self:
            if not rec.menuproId:
                continue

            payload = {
                "odoo_id": rec.id,
                "menuProName": rec.name,
                "sequence": rec.sequence,
                "html_color": rec.html_color or "",
                "is_custom": rec.is_custom,
                "status": "active" if rec.active else "archived",
                "active": rec.active,
                "default_extra_price": rec.default_extra_price,
                "restaurant_id": cfg['restaurant_id'],
            }

            try:
                url = f"{cfg['attributs_url']}/attribut-values/{rec.menuproId}"
                rec._call_mp("PATCH", url, payload)
                _logger.info("✅ Sync OK for product.attribute.value %s", rec.id)
            except Exception as e:
                _logger.warning("❌ Sync failed for product.attribute.value %s: %s", rec.id, e)

        return res







