from odoo import models, fields, api, tools
import requests
from ..utils import image_utils


class PosCategory(models.Model):
    _inherit = 'pos.category'

    option_name = fields.Selection(selection='_fetch_categories_from_api', string='Nom de la catégorie')
    menupro_id = fields.Char(string='MenuPro ID')
    picture = fields.Char(string='Picture')
    type_name = fields.Char(string='Type Name')

    @api.model
    def _fetch_categories_from_api(self):
        """ This will be used to display the Menupro Categories to the user in a select field so the user can choose
        one of them."""
        try:
            get_level_category_url = tools.config.get('get_level_category_url')
            # Level 3 is meant for the menus categories (i.e. Burgers, Plats, Fruits de mer, Pizzas ect..)
            level = 3
            if get_level_category_url is None:
                return []

            response = requests.get(get_level_category_url + str(level))
            response.raise_for_status()
            categories = response.json()

            # Prepare a list of tuples with the category IDs and names
            category_options = [(str(category['_id']), category['menuProName']) for category in categories]
            return category_options

        except requests.exceptions.RequestException:
            return []

    def _fetch_category_data_by_id(self, category_id):
        """ This method fetch the category infos selected by the user """
        try:
            get_category_by_id = tools.config.get('get_category_by_id_url')
            if get_category_by_id is None:
                return "There is no get_category_by_id_url in Config"

            response = requests.get(get_category_by_id + str(category_id))
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException:
            return None

    def create_pos_category(self, vals_list):
        return super(PosCategory, self).create(vals_list)

    def write_pos_category(self, vals):
        return super(PosCategory, self).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        base_s3_url = tools.config.get('base_s3_url', '')
        for vals in vals_list:  # ← on boucle
            option = vals.get('option_name')
            if option:
                data = self._fetch_category_data_by_id(option)
                if data:
                    # Image en base64 si dispo
                    img128 = None
                    if data.get('picture'):
                        img128 = image_utils.get_image_as_base64(
                            f"{base_s3_url}{data['picture']}"
                        )
                    # Enrichir les valeurs avant le super()
                    vals.update({
                        'name': data.get('menuProName', ''),
                        'menupro_id': data.get('_id'),
                        'picture': f"{base_s3_url}{data.get('picture', '')}",
                        'image_128': img128,
                        'type_name': data.get('typeName', ''),
                    })
        
        # Create POS categories first
        pos_categories = super().create(vals_list)
        
        # Create corresponding product categories (avoid infinite loop)
        for pos_category in pos_categories:
            if not self.env.context.get('skip_product_sync'):
                self._create_corresponding_product_category(pos_category)
        
        return pos_categories

    def write(self, vals):
        option = vals.get('option_name')
        if option:
            base_s3_url = tools.config.get('base_s3_url', '')
            data = self._fetch_category_data_by_id(option)
            if data:
                img128 = None
                if data.get('picture'):
                    img128 = image_utils.get_image_as_base64(
                        f"{base_s3_url}{data['picture']}"
                    )
                vals.update({
                    'name': data.get('menuProName', ''),
                    'menupro_id': data.get('_id'),
                    'picture': f"{base_s3_url}{data.get('picture','')}",
                    'image_128': img128,
                    'type_name': data.get('typeName', ''),
                })
        
        result = super().write(vals)
        
        # Update corresponding product category if name or menupro_id changed
        if not self.env.context.get('skip_product_sync') and ('name' in vals or 'menupro_id' in vals):
            for pos_category in self:
                self._update_corresponding_product_category(pos_category, vals)
        
        return result

    def _create_corresponding_product_category(self, pos_category):
        """ Create a corresponding product category with same name and menupro_id """
        # Check if product category already exists with same menupro_id
        existing_product_category = self.env['product.category'].search([
            ('menupro_id', '=', pos_category.menupro_id)
        ], limit=1)
        
        if not existing_product_category and pos_category.menupro_id:
            # Create new product category with context to avoid infinite loop
            product_category_vals = {
                'name': pos_category.name,
                'menupro_id': pos_category.menupro_id,
                'picture': pos_category.picture,
                'type_name': pos_category.type_name,
            }
            self.env['product.category'].with_context(skip_pos_sync=True).create(product_category_vals)

    def _update_corresponding_product_category(self, pos_category, vals):
        """ Update corresponding product category with same menupro_id """
        if pos_category.menupro_id:
            product_category = self.env['product.category'].search([
                ('menupro_id', '=', pos_category.menupro_id)
            ], limit=1)
            
            if product_category:
                update_vals = {}
                if 'name' in vals:
                    update_vals['name'] = pos_category.name
                if 'menupro_id' in vals:
                    update_vals['menupro_id'] = pos_category.menupro_id
                if 'picture' in vals:
                    update_vals['picture'] = pos_category.picture
                if 'type_name' in vals:
                    update_vals['type_name'] = pos_category.type_name
                
                if update_vals:
                    product_category.with_context(skip_pos_sync=True).write(update_vals)