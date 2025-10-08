import logging
import re

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
    max_discount = fields.Float(string='Remise maximum', default=0.0)
    menupro_id = fields.Char(string='MenuPro ID')
    is_mobile_default = fields.Boolean(string='Code promo mobile par défaut', default=False, help="Identifie le code promo par défaut pour les commandes mobile self-order")
    
    # Type de limitation
    limitation_type = fields.Selection([
        ('usage', 'Limitation par nombre d\'utilisations'),
        ('dates', 'Limitation par dates'),
        ('always', 'Toujours disponible (illimité)'),
    ], string='Type de limitation', default='always', required=True, 
       help="Choisissez comment limiter l'utilisation de ce code promo")
    
    # Champs de limitation par dates
    expiration_date = fields.Date(string='Date d\'expiration', help="Date d'expiration de la remise")
    start_date = fields.Date(string='Date de début', help="Date de début de la remise")
    
    # Champs de limitation par usage
    max_usage = fields.Integer(string='Nombre d\'utilisations max', default=0, help="Nombre maximum d'utilisations du code (0 = épuisé)")
    
    # Champs calculés/anciens (pour compatibilité)
    always_available = fields.Boolean(string='Toujours disponible', compute='_compute_always_available', store=True)
    dates_readonly = fields.Boolean(compute='_compute_fields_readonly', store=False)
    usage_readonly = fields.Boolean(compute='_compute_fields_readonly', store=False)

    _sql_constraints = [
        ('discount_code_uniq', 'unique(discount_code)', "Le code de remise doit être unique !"),
    ]

    @api.depends('limitation_type')
    def _compute_always_available(self):
        """Calcule always_available pour compatibilité avec l'ancien code"""
        for record in self:
            record.always_available = (record.limitation_type == 'always')

    @api.depends('limitation_type')
    def _compute_fields_readonly(self):
        """Gère les champs readonly selon le type de limitation"""
        for record in self:
            record.dates_readonly = (record.limitation_type != 'dates')
            record.usage_readonly = (record.limitation_type != 'usage')

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
            "isMobileDefault": self.is_mobile_default,
            "limitationType": self.limitation_type,
            "expirationDate": self.expiration_date,
            "startDate": self.start_date,
            "alwaysAvailable": self.always_available,
            "maxUsage": self.max_usage,
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

    @api.constrains('enabled', 'start_date', 'expiration_date', 'max_usage', 'limitation_type')
    def _check_activation_rules(self):
        for record in self:
            if not record.enabled:
                continue
            
            # Validation selon le type de limitation
            if record.limitation_type == 'dates':
                # Mode dates : vérifier les dates
                today = fields.Date.context_today(record)
                
                if not record.start_date and not record.expiration_date:
                    raise ValidationError(
                        f"Pour le code '{record.discount_code}', vous devez définir au moins une date "
                        f"(début ou expiration) en mode 'Limitation par dates'."
                    )
                
                if record.start_date and record.start_date > today:
                    raise ValidationError(
                        f"Impossible d'activer le code '{record.discount_code}'. "
                        f"La date de début ({record.start_date}) n'est pas encore atteinte."
                    )
                
                if record.expiration_date and record.expiration_date < today:
                    raise ValidationError(
                        f"Impossible d'activer le code '{record.discount_code}'. "
                        f"La date d'expiration ({record.expiration_date}) est dépassée."
                    )
            
            elif record.limitation_type == 'usage':
                # Mode usage : vérifier le nombre d'utilisations
                if record.max_usage is None or record.max_usage <= 0:
                    raise ValidationError(
                        f"Impossible d'activer le code '{record.discount_code}'. "
                        f"Le nombre d'utilisations maximum est atteint ou invalide. "
                        f"Définissez un nombre > 0."
                    )
            
            # Mode 'always' : pas de validation particulière

    def write(self, vals):
        if 'restaurant_id' in vals:
            del vals['restaurant_id']

        res = super().write(vals)

        cfg = self._get_config()
        base = cfg['restaurant-discount_url']

        for rec in self:
            try:
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

        _logger.info(f"🔍 Recherche code promo: {discount_code} pour restaurant: {restaurant_id}")

        config = self.search([
            ('restaurant_id', '=', restaurant_id),
            ('discount_code', '=', discount_code),
            ('enabled', '=', True)
        ], limit=1)

        if not config:
            _logger.warning(f"❌ Code promo {discount_code} NON TROUVÉ ou DÉSACTIVÉ pour restaurant_id={restaurant_id}")
            # Chercher sans le filtre enabled pour debug
            config_any = self.search([
                ('restaurant_id', '=', restaurant_id),
                ('discount_code', '=', discount_code),
            ], limit=1)
            if config_any:
                _logger.warning(f"⚠️ Code promo existe mais enabled={config_any.enabled}")
            return self._get_default_config()

        # Vérifier si le code est vraiment actif (dates et usage)
        _logger.info(f"✅ Code promo {discount_code} trouvé: enabled={config.enabled}, max_usage={config.max_usage}, always_available={config.always_available}, start_date={config.start_date}, expiration_date={config.expiration_date}")
        
        if not config.is_promo_active():
            today = fields.Date.context_today(config)
            _logger.warning(f"❌ Code promo {discount_code} trouvé mais NON ACTIF:")
            _logger.warning(f"   - enabled: {config.enabled}")
            _logger.warning(f"   - max_usage: {config.max_usage} (doit être > 0 si défini)")
            _logger.warning(f"   - always_available: {config.always_available}")
            _logger.warning(f"   - start_date: {config.start_date} (aujourd'hui: {today})")
            _logger.warning(f"   - expiration_date: {config.expiration_date} (aujourd'hui: {today})")
            return self._get_default_config()

        _logger.info(f"✅ Code promo {discount_code} VALIDE et ACTIF - {config.discount_percentage}% de remise")
        return {
            'enabled': config.enabled,
            'discount_percentage': config.discount_percentage,
            'discount_name': config.discount_name,
            'min_amount': config.min_amount,
            'max_discount': config.max_discount or None,
            'expiration_date': config.expiration_date or None,
            'start_date': config.start_date or None,
            'max_usage': config.max_usage,
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

    @api.constrains('max_usage')
    def _check_max_usage(self):
        for record in self:
            if record.max_usage is not None and record.max_usage < 0:
                raise ValidationError("Le nombre maximum d'utilisations ne peut pas être négatif")

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
        
        # Vérifier selon le type de limitation
        if self.limitation_type == 'usage':
            # Mode usage : vérifier le compteur d'utilisations
            if self.max_usage is None or self.max_usage <= 0:
                return False
        
        elif self.limitation_type == 'dates':
            # Mode dates : vérifier les dates
            if self.start_date and check_date < self.start_date:
                return False
            if self.expiration_date and check_date > self.expiration_date:
                return False
        
        # Mode 'always' : toujours actif si enabled
        return True

    def decrement_usage(self):
        """Décrémente le compteur d'utilisation du code promo (uniquement en mode 'usage')"""
        self.ensure_one()
        
        # Ne décrementer que si le code utilise la limitation par usage
        if self.limitation_type != 'usage':
            _logger.info(f"Code promo {self.discount_code}: pas de décrément (mode {self.limitation_type})")
            return
        
        if self.max_usage > 0:
            new_usage = self.max_usage - 1
            # Utiliser SQL directe pour éviter les contraintes et améliorer les performances
            self.env.cr.execute(
                "UPDATE restaurant_discount_config SET max_usage = %s, enabled = %s WHERE id = %s",
                (new_usage, False if new_usage == 0 else self.enabled, self.id)
            )
            self.invalidate_recordset(['max_usage', 'enabled'])
            _logger.info(f"Code promo {self.discount_code}: utilisations restantes = {new_usage}")
            if new_usage == 0:
                _logger.info(f"Code promo {self.discount_code} automatiquement désactivé (limite atteinte)")

    @api.model
    def cron_deactivate_expired_codes(self):
        """CRON job pour désactiver automatiquement les codes expirés"""
        today = fields.Date.context_today(self)
        
        # Désactiver les codes expirés par date (mode 'dates' uniquement)
        expired_by_date = self.search([
            ('enabled', '=', True),
            ('limitation_type', '=', 'dates'),
            ('expiration_date', '<', today)
        ])
        
        if expired_by_date:
            expired_by_date.write({'enabled': False})
            _logger.info(f"Codes expirés par date désactivés: {len(expired_by_date)} code(s) - {expired_by_date.mapped('discount_code')}")
        
        # Désactiver les codes ayant atteint leur limite d'utilisation (mode 'usage' uniquement)
        # Note: decrement_usage() désactive déjà automatiquement quand max_usage atteint 0
        # Mais on vérifie quand même au cas où
        usage_limit_reached = self.search([
            ('enabled', '=', True),
            ('limitation_type', '=', 'usage'),
            ('max_usage', '<=', 0)
        ])
        
        if usage_limit_reached:
            usage_limit_reached.write({'enabled': False})
            _logger.info(f"Codes épuisés désactivés: {len(usage_limit_reached)} code(s) - {usage_limit_reached.mapped('discount_code')}")
        
        return True

