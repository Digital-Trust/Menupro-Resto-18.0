from odoo import models, fields, api
from odoo.exceptions import ValidationError


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

    _sql_constraints = [
        ('discount_code_uniq', 'unique(discount_code)', "Le code de remise doit être unique !"),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
        for vals in vals_list:
            if restaurant_id:
                vals['restaurant_id'] = restaurant_id
        return super().create(vals_list)

    @api.constrains('enabled', 'discount_percentage')
    def _check_enabled_discount_percentage(self):
        for record in self:
            if record.enabled and (record.discount_percentage is None or record.discount_percentage <= 0):
                raise ValidationError(
                    "Le pourcentage de remise doit être renseigné et supérieur à 0 si la remise est activée.")

    def write(self, vals):
        # Empêcher la modification du restaurant_id
        if 'restaurant_id' in vals:
            del vals['restaurant_id']
        return super().write(vals)

    @api.model
    def get_config_for_code(self, restaurant_id=None, discount_code=None):
        if not restaurant_id:
            restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
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
        restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
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
