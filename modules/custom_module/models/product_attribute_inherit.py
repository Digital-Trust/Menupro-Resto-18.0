from odoo import models, fields, api, tools
import requests
import logging

from odoo.exceptions import UserError
from odoo.http import request
from ..utils.security_utils import mask_sensitive_data
from ..utils.config_cache import ConfigCache

_logger = logging.getLogger(__name__)


class ProductAttribute(models.Model):
    _inherit = 'product.attribute'
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
                for v in self.value_ids
            ],
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

        # Skip sync if triggered by value sync
        if self.env.context.get('skip_attribute_menupro_sync'):
            _logger.debug("⏭️ Skipping attribute sync (triggered by value)")
            return records

        cfg = self._get_config()
        base = cfg['attributs_url']

        for rec in records:
            # Create with empty values first
            payload = rec._build_payload()
            payload['values'] = []

            data = rec._call_mp("POST", base, payload)
            rec.menuproId = data.get("_id")

            # Now update with values if any exist
            if rec.value_ids:
                # Use context to prevent value write from triggering attribute sync
                rec.with_context(skip_attribute_menupro_sync=True)._sync_values_to_menupro()

        return records

    def _sync_values_to_menupro(self):
        """Sync values to MenuPro after attribute is created."""
        self.ensure_one()
        if not self.menuproId:
            _logger.warning("⚠️ Cannot sync values: attribute has no MenuPro ID")
            return

        cfg = self._get_config()
        base = cfg['attributs_url']

        payload = self._build_payload()
        response = self._call_mp("PATCH", f"{base}/{self.menuproId}", payload)

        # Map MenuPro IDs back to values
        if response and "values" in response:
            vmap = {v["odoo_id"]: v["_id"] for v in response["values"]}
            for val in self.value_ids:
                menupro_id = vmap.get(val.id)
                if menupro_id and not val.menuproId:
                    # Use context to prevent triggering attribute sync
                    val.with_context(skip_attribute_menupro_sync=True).menuproId = menupro_id
                    _logger.info("🆕 Attribution du MenuPro ID à val.id=%s → %s", val.id, menupro_id)

    def write(self, vals):
        # Skip sync if triggered by value sync
        if self.env.context.get('skip_attribute_menupro_sync'):
            _logger.debug("⏭️ Skipping attribute sync (triggered by value)")
            return super().write(vals)

        res = super().write(vals)
        cfg = self._get_config()
        base = cfg['attributs_url']

        for rec in self:
            payload = rec._build_payload()

            if not rec.menuproId:
                payload['values'] = []
                response = rec._call_mp("POST", base, payload)
                rec.menuproId = response.get("_id")

                if rec.value_ids:
                    rec.with_context(skip_attribute_menupro_sync=True)._sync_values_to_menupro()
            else:
                response = rec._call_mp("PATCH", f"{base}/{rec.menuproId}", payload)

                if response and "values" in response:
                    vmap = {v["odoo_id"]: v["_id"] for v in response["values"]}
                    for val in rec.value_ids:
                        if not val.menuproId and val.id in vmap:
                            val.with_context(skip_attribute_menupro_sync=True).menuproId = vmap[val.id]
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