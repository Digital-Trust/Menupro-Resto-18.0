import logging

import requests

from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

class RestaurantDiscountConfig(models.Model):
    _name = 'restaurant.discount.config'
    _description = 'Configuration de remise QR mobile'
    _rec_name = 'discount_name'

    restaurant_id = fields.Char(string='Restaurant ID', readonly=True)
    discount_code = fields.Char(string="Code de remise", required=True, index=True, help="Code unique pour appliquer cette remise")
    enabled = fields.Boolean(string='Remise activée', default=False)
    discount_percentage = fields.Float(string='Pourcentage de remise (%)', default=0.0)
    discount_name = fields.Char(string='Nom de la remise', default='Remise QR Mobile')
    min_amount = fields.Float(string='Montant minimum', default=0.0)
    max_discount = fields.Float(string='Remise maximum (€)', default=0.0)
    menupro_id = fields.Char(string='MenuPro ID')


    _sql_constraints = [
        ('discount_code_uniq', 'unique(discount_code)', "Le code de remise doit être unique !"),
    ]

    def _get_config(self):
        """Charge et valide la config une seule fois par thread."""
        if hasattr(self.env, "_mp_config"):
            return self.env._mp_config

        ICParam = self.env['ir.config_parameter'].sudo()

        cfg = {
            'restaurant-discount_url': tools.config.get('restaurant-discount_url'),
            'secret_key': tools.config.get('secret_key'),
            'odoo_secret_key': tools.config.get('odoo_secret_key'),
            'restaurant_id': ICParam.get_param('restaurant_id'),
        }

        for k, v in cfg.items():
            if not v:
                _logger.error("%s is missing in config", k)
                raise UserError(f"L’option '{k}' est manquante dans la configuration.")

        self.env._mp_config = cfg
        _logger.info("\033[92mMenuPro config OK\033[0m")
        return cfg

    def _build_payload(self):
        cfg = self._get_config()
        self.ensure_one()
        return {
            "odooId": self.id,
            "restaurantId": self.restaurant_id,
            "discountCode": self.discount_code,
            "enabled": self.enabled,
            "discountPercentage": self.discount_percentage,
            "discountName": self.discount_name,
            "minAmount": self.min_amount,
            "maxDiscount": self.max_discount,


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
        cfg = self._get_config()
        base = cfg['restaurant-discount_url']
        restaurant_id = cfg['restaurant_id']

        for vals in vals_list:
            if restaurant_id:
                vals['restaurant_id'] = restaurant_id
        records = super().create(vals_list)
        for record in records:
            try:
                data = record._call_mp("POST", base, record._build_payload())
                record.menupro_id = data.get("_id")
            except Exception as e:
                _logger.error("Failed to sync discount config %s with MenuPro: %s", record.id, e)


        return records

        return super().create(vals_list)

    @api.constrains('enabled', 'discount_percentage')
    def _check_enabled_discount_percentage(self):
        for record in self:
            if record.enabled and (record.discount_percentage is None or record.discount_percentage <= 0):
                raise ValidationError(
                    "Le pourcentage de remise doit être renseigné et supérieur à 0 si la remise est activée.")

    def write(self, vals):
        if 'restaurant_id' in vals:
            del vals['restaurant_id']
        res = super().write(vals)

        cfg = self._get_config()
        base = cfg['restaurant-discount_url']

        for rec in self:
            if not rec.menupro_id:
                continue
            try:
                payload = rec._build_payload()
                rec._call_mp("PATCH", f"{base}/{rec.menupro_id}", payload)
            except Exception as e:
                _logger.error("Failed to sync discount config %s with MenuPro: %s", rec.id, e)
        return res

    @api.model
    def get_config_for_code(self, restaurant_id=None, discount_code=None):
        cfg = self._get_config()
        if not restaurant_id:
            restaurant_id = cfg['restaurant_id']
        if not discount_code:
            return self._get_default_config()

        config = self.search([
            ('restaurant_id', '=', restaurant_id),
            ('discount_code', '=', discount_code),
            ('enabled', '=', True)
        ], limit=1)

        if not config:
            return self._get_default_config()

        return {
            'enabled': config.enabled,
            'discount_percentage': config.discount_percentage,
            'discount_name': config.discount_name,
            'min_amount': config.min_amount,
            'max_discount': config.max_discount or None,
        }

    def _get_default_config(self):
        """Configuration par défaut si aucune configuration n'est trouvée"""
        return {
            'enabled': False,
            'discount_percentage': 0.0,
            'discount_name': 'Remise QR Mobile',
            'min_amount': 0.0,
            'max_discount': None,
        }

    @api.model
    def ensure_config_exists(self):
        cfg = self._get_config()
        restaurant_id = cfg['restaurant_id']
        if not restaurant_id:
            return False
        existing_config = self.search([('restaurant_id', '=', restaurant_id)], limit=1)
        if not existing_config:
            self.create({
                'restaurant_id': restaurant_id,
                'enabled': False,
                'discount_percentage': 0.0,
                'discount_name': 'Remise QR Mobile',
                'min_amount': 0.0,
                'max_discount': 0.0,
                'discount_code': 'DEFAULT',
            })
        return True

    @api.constrains('discount_percentage')
    def _check_discount_percentage(self):
        for record in self:
            if record.discount_percentage < 0 or record.discount_percentage > 100:
                raise ValidationError("Le pourcentage de remise doit être entre 0 et 100%")

    @api.constrains('min_amount', 'max_discount')
    def _check_amounts(self):
        for record in self:
            if record.min_amount < 0:
                raise ValidationError("Le montant minimum ne peut pas être négatif")
            if record.max_discount < 0:
                raise ValidationError("La remise maximum ne peut pas être négative")

    @api.ondelete(at_uninstall=False)
    def _unlink(self):
        """Called automatically before unlink - sync deletion with external service"""
        cfg = self._get_config()
        base = cfg['restaurant-discount_url']

        for rec in self:
            if rec.menupro_id:
                try:
                    headers = {
                        "x-secret-key": cfg['secret_key'],
                        "x-odoo-secret-key": cfg['odoo_secret_key'],
                    }
                    resp = requests.request(
                        "DELETE",
                        f"{base}/{rec.menupro_id}",
                        headers=headers,
                        timeout=10
                    )
                    resp.raise_for_status()
                    _logger.info("Successfully deleted discount config %s from MenuPro", rec.menupro_id)
                except Exception as e:
                    _logger.error("Failed to delete discount config %s from MenuPro: %s", rec.menupro_id, e)