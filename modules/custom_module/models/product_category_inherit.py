from odoo import models, fields, api, tools
import requests
import logging

_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    menupro_id = fields.Char(string='MenuPro ID')
    picture = fields.Char(string='Picture')
    type_name = fields.Char(string='Type Name')

    @api.model
    def create_from_api_data(self, category_data):
        """ Create or update POS categories from API data. """
        for data in category_data:
            category = self.search([('id', '=', data['id'])], limit=1)
            if category:
                category.write(data)
            else:
                self.create(data)

    @api.model_create_multi
    def create(self, vals_list):
        """ Override create to automatically create corresponding POS category and get menupro_id """
        # Create product categories first
        categories = super().create(vals_list)
        
        for category in categories:
            if not self.env.context.get('skip_pos_sync'):
                self._create_in_menupro_and_pos_category(category)
        
        return categories

    def write(self, vals):
        """ Override write to update corresponding POS category """
        result = super().write(vals)
        
        # Update corresponding POS category if name or menupro_id changed
        if not self.env.context.get('skip_pos_sync') and ('name' in vals or 'menupro_id' in vals):
            for category in self:
                self._update_corresponding_pos_category(category, vals)
        
        return result

    def _create_in_menupro_and_pos_category(self, product_category):
        """ Create category in MenuPro API and then create corresponding POS category """
        try:
            # Create category in MenuPro API
            menupro_id = self._create_category_in_menupro(product_category)
            
            if menupro_id:
                # Update product category with menupro_id
                product_category.with_context(skip_pos_sync=True).write({
                    'menupro_id': menupro_id
                })
                print(f"Updated product category {product_category.name} with menupro_id: {menupro_id}")
                
                # Create corresponding POS category
                self._create_corresponding_pos_category(product_category, menupro_id)
            else:
                print(f"Failed to create category in MenuPro for: {product_category.name}")
                
        except Exception as e:
            _logger.error(f"Error creating category in MenuPro: {e}")
            print(f"Error creating category in MenuPro: {e}")

    def _create_category_in_menupro(self, product_category):
        """ Create category in MenuPro API and return menupro_id """
        try:
            create_category_url = "https://api.menupro.tn/category"
            odoo_secret_key = tools.config.get("odoo_secret_key")
            
            if not odoo_secret_key:
                _logger.error("odoo_secret_key missing in config")
                return None
            
            # Prepare data for MenuPro API
            data = {
                'menuProName': product_category.name,
                'level': 3,
                'status': 'PUBLISHED',
            }
            
            # Add picture if available
            if product_category.picture:
                data['picture'] = product_category.picture
            
            # Add type_name if available
            if product_category.type_name:
                data['typeName'] = product_category.type_name
            
            headers = {
                'Content-Type': 'application/json',
                'x-odoo-key': odoo_secret_key
            }
            
            print(f"Creating category in MenuPro: {data}")
            response = requests.post(create_category_url, json=data, headers=headers)
            
            if response.status_code == 200 or response.status_code == 201:
                response_data = response.json()
                menupro_id = response_data.get('id') or response_data.get('_id')
                print(f"Successfully created category in MenuPro with ID: {menupro_id}")
                return menupro_id
            else:
                _logger.error(f"Failed to create category in MenuPro. Status: {response.status_code}, Response: {response.text}")
                print(f"Failed to create category in MenuPro. Status: {response.status_code}, Response: {response.text}")
                return None
                
        except Exception as e:
            _logger.error(f"Exception while creating category in MenuPro: {e}")
            print(f"Exception while creating category in MenuPro: {e}")
            return None

    def _create_corresponding_pos_category(self, product_category, menupro_id):
        """ Create a corresponding POS category with menupro_id """
        # Check if POS category already exists with same menupro_id
        existing_pos_category = self.env['pos.category'].search([
            ('menupro_id', '=', menupro_id)
        ], limit=1)
        
        if not existing_pos_category:
            # Create new POS category with context to avoid infinite loop
            pos_category_vals = {
                'name': product_category.name,
                'menupro_id': menupro_id,
                'picture': product_category.picture,
                'type_name': product_category.type_name,
            }
            pos_category = self.env['pos.category'].with_context(skip_product_sync=True).create(pos_category_vals)
            print(f"Created POS category: {pos_category.name} with menupro_id: {menupro_id}")
        else:
            print(f"POS category already exists with menupro_id: {menupro_id}")

    def _update_corresponding_pos_category(self, product_category, vals):
        """ Update corresponding POS category with same menupro_id """
        if product_category.menupro_id:
            pos_category = self.env['pos.category'].search([
                ('menupro_id', '=', product_category.menupro_id)
            ], limit=1)
            print("pos_category =>", pos_category)
            if pos_category:
                update_vals = {}
                if 'name' in vals:
                    update_vals['name'] = product_category.name
                if 'menupro_id' in vals:
                    update_vals['menupro_id'] = product_category.menupro_id
                if 'picture' in vals:
                    update_vals['picture'] = product_category.picture
                if 'type_name' in vals:
                    update_vals['type_name'] = product_category.type_name
                
                if update_vals:
                    pos_category.with_context(skip_product_sync=True).write(update_vals)