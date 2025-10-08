import logging
import re

import requests

from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError, UserError
from ..utils.security_utils import mask_sensitive_data

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
    max_discount = fields.Float(string='Remise maximum', default=0.0)
    menupro_id = fields.Char(string='MenuPro ID')
    is_mobile_default = fields.Boolean(string='Code promo mobile par défaut', default=False, help="Identifie le code promo par défaut pour les commandes mobile self-order")
    expiration_date = fields.Date(string='Date d\'expiration', help="Date d'expiration de la remise")
    start_date = fields.Date(string='Date de début', help="Date de début de la remise")

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
                raise UserError(f"L'option '{k}' est manquante dans la configuration.")

        self.env._mp_config = cfg
        masked_cfg = mask_sensitive_data(cfg)
        _logger.info("\033[92mMenuPro config OK: %s\033[0m", masked_cfg)
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
            "isMobileDefault": self.is_mobile_default,
            "expirationDate": self.expiration_date,
            "startDate": self.start_date,
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

        try:
            for rec in self:
                payload = rec._build_payload()

                if not rec.menupro_id:
                    response = rec._call_mp("POST", base, payload)
                    rec.menupro_id = response.get("_id")
                else:
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
            'expiration_date': config.expiration_date or None,
            'start_date': config.start_date or None,
        }

    @api.model
    def get_default_mobile_promo_config(self, restaurant_id=None):
        """
        Récupère la configuration du code promo par défaut pour mobile self-order
        
        :param restaurant_id: ID du restaurant
        :return: dict avec la configuration de remise par défaut pour mobile
        """
        cfg = self._get_config()
        if not restaurant_id:
            restaurant_id = cfg['restaurant_id']
        
        _logger.info(f"🔍 Recherche code promo mobile par défaut (is_mobile_default=True) pour restaurant_id: {restaurant_id}")
        
        config = self.search([
            ('restaurant_id', '=', restaurant_id),
            ('is_mobile_default', '=', True),
            ('enabled', '=', True)
        ], limit=1)

        if not config:
            _logger.warning(f"⚠️ Aucun code promo mobile par défaut trouvé pour restaurant_id={restaurant_id}")
            _logger.info("Vérifiez qu'un code promo avec is_mobile_default=True existe et est activé")
            # Si pas de configuration trouvée, retourner une configuration par défaut
            return {
                'enabled': False,
                'discount_percentage': 0.0,
                'discount_name': 'Remise Mobile Self-Order',
                'min_amount': 0.0,
                'max_discount': None,
                'expiration_date': None,
                'start_date': None,
            }
        
        _logger.info(f"✅ Code promo mobile par défaut trouvé: {config.discount_name} ({config.discount_code}), {config.discount_percentage}%, min={config.min_amount}")

        return {
            'enabled': config.enabled,
            'discount_percentage': config.discount_percentage,
            'discount_name': config.discount_name,
            'discount_code': config.discount_code,
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
            'expiration_date': None,
            'start_date': None,
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
                'expiration_date': None,
                'start_date': None,
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


    @api.constrains('discount_name')
    def _check_discount_name_contains_remise(self):
        for record in self:
            if not record.discount_name:
                raise ValidationError("Le nom de la remise ne peut pas être vide.")
            if not re.search(r'\bremise\b', record.discount_name, re.IGNORECASE):
                raise ValidationError("Le nom de la remise doit contenir le mot 'Remise'.")

    @api.constrains('is_mobile_default')
    def _check_single_mobile_default(self):
        """Vérifie qu'il n'y a qu'un seul code promo mobile par défaut par restaurant"""
        for record in self:
            if record.is_mobile_default and record.restaurant_id:
                # Chercher d'autres codes promo mobile par défaut pour le même restaurant
                other_defaults = self.env['restaurant.discount.config'].search([
                    ('restaurant_id', '=', record.restaurant_id),
                    ('is_mobile_default', '=', True),
                    ('id', '!=', record.id)
                ])
                
                if other_defaults:
                    raise ValidationError(
                        f"Il ne peut y avoir qu'un seul code promo mobile par défaut par restaurant. "
                        f"Le code '{other_defaults[0].discount_name}' est déjà configuré comme mobile par défaut."
                    )

    @api.constrains('start_date', 'expiration_date')
    def _check_date_validity(self):
        """Vérifie que la date de début est antérieure à la date d'expiration"""
        for record in self:
            if record.start_date and record.expiration_date:
                if record.start_date > record.expiration_date:
                    raise ValidationError(
                        "La date de début doit être antérieure à la date d'expiration."
                    )

    def is_promo_active(self, check_date=None):
        """
        Vérifie si le code promo est actif à une date donnée
        
        :param check_date: Date à vérifier (par défaut, date du jour)
        :return: True si le code promo est actif, False sinon
        """
        if not check_date:
            check_date = fields.Date.context_today(self)
        
        # Vérifier si le code promo est activé
        if not self.enabled:
            return False
        
        # Vérifier la date de début
        if self.start_date and check_date < self.start_date:
            return False
        
        # Vérifier la date d'expiration
        if self.expiration_date and check_date > self.expiration_date:
            return False
        
        return True

