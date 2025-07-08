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
        return super().create(vals_list)

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
                    'name'      : data.get('menuProName', ''),
                    'menupro_id': data.get('_id'),
                    'picture'   : f"{base_s3_url}{data.get('picture','')}",
                    'image_128' : img128,
                    'type_name' : data.get('typeName', ''),
                })
        return super().write(vals)
