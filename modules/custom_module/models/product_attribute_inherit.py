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

    def _build_payload(self, include_values=True):
        """Build payload for MenuPro API.

        Args:
            include_values: If False, don't include values (useful during creation)
        """
        cfg = self._get_config()
        self.ensure_one()

        payload = {
            "odoo_id": self.id,
            "menuProName": self.name,
            "create_variant": self.create_variant,
            "display_type": self.display_type,
            "sequence": self.sequence,
            "status": "active" if self.active else "archived",
            "active": self.active,
            "restaurant_id": cfg['restaurant_id'],
        }

        if include_values:
            values_list = []
            for v in self.value_ids:
                # Skip values without real IDs (being created in same transaction)
                if not v.id or isinstance(v.id, models.NewId):
                    _logger.debug("Skipping value without real ID: %s", v.name)
                    continue

                values_list.append({
                    "odoo_id": v.id,
                    "menuProName": v.name,
                    "sequence": v.sequence,
                    "html_color": v.html_color or "",
                    "is_custom": v.is_custom,
                    "status": "active" if v.active else "archived",
                    "active": v.active,
                    "default_extra_price": v.default_extra_price,
                    "restaurant_id": cfg['restaurant_id'],
                })
            payload["values"] = values_list
        return payload

    def _call_mp(self, method, url, json=None):
        cfg = self._get_config()
        headers = {
            "x-secret-key": cfg['secret_key'],
            "x-odoo-secret-key": cfg['odoo_secret_key'],
        }
        try:
            _logger.info("MenuPro API call: %s %s with payload: %s", method, url, json)
            resp = requests.request(method, url, json=json, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.exceptions.HTTPError as e:
            _logger.error("MenuPro API error: %s - Response: %s", e, e.response.text if e.response else 'No response')
            raise
        except Exception as e:
            _logger.warning("MenuPro %s %s failed → %s", method, url, e)
            raise

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        cfg = self._get_config()
        base = cfg['attributs_url']

        for rec in records:
            # First create attribute without values (values might not have IDs yet)
            payload = rec._build_payload(include_values=False)
            payload["values"] = []  # Empty values array for initial creation

            data = rec._call_mp("POST", base, payload)
            rec.menuproId = data.get("_id")

            # Now update with values if they exist and have IDs
            if rec.value_ids:
                # Force flush to ensure value IDs are assigned
                self.env.flush_all()

                # Update with values
                update_payload = rec._build_payload(include_values=True)
                if update_payload.get("values"):
                    response = rec._call_mp("PATCH", f"{base}/{rec.menuproId}", update_payload)

                    # Map MenuPro IDs back to values
                    vmap = {v["odoo_id"]: v["_id"] for v in response.get("values", [])}
                    for val in rec.value_ids:
                        menupro_id = vmap.get(val.id)
                        if menupro_id:
                            val.menuproId = menupro_id
                            _logger.info("🆕 Attribution du MenuPro ID à val.id=%s → %s", val.id, menupro_id)

        return records

    def write(self, vals):
        res = super().write(vals)
        cfg = self._get_config()
        base = cfg['attributs_url']

        for rec in self:
            # Ensure all records are flushed
            self.env.flush_all()

            payload = rec._build_payload(include_values=True)

            if not rec.menuproId:
                response = rec._call_mp("POST", base, payload)
                rec.menuproId = response.get("_id")
            else:
                response = rec._call_mp("PATCH", f"{base}/{rec.menuproId}", payload)

            # Map MenuPro IDs back to values
            if response and "values" in response:
                vmap = {v["odoo_id"]: v["_id"] for v in response["values"]}
                values_to_update = []
                for val in rec.value_ids:
                    if not val.menuproId and val.id in vmap:
                        values_to_update.append((val, vmap[val.id]))

                for val, menupro_id in values_to_update:
                    val.menuproId = menupro_id
                    _logger.info("🆕 Attribution du MenuPro ID à val.id=%s → %s", val.id, menupro_id)
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
