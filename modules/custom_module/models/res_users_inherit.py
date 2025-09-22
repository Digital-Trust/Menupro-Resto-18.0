from odoo import models, fields, api
import secrets


class ResUsers(models.Model):
    _inherit = 'res.users'

    api_key = fields.Char(
        string='API Key',
        copy=False,
        readonly=True,
        index=True,
    )

    def generate_api_key(self):
        """Génère et assigne une nouvelle clé API sécurisée"""
        for user in self:
            user.api_key = secrets.token_hex(32)  # 64 caractères hex
        return True

    @api.model
    def check_api_key(self, key):
        """Vérifie si une clé API est valide et retourne l’utilisateur"""
        if not key:
            return None
        return self.sudo().search([('api_key', '=', key)], limit=1)
