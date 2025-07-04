from odoo import models, fields


class ProductTemplateAttributeExclusion(models.Model):
    _inherit = 'product.template.attribute.exclusion'
    menuproId = fields.Char(string="MenuPro ID", copy=False)
