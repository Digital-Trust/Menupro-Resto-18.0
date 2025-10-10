from odoo import models, fields, api, tools, http
import requests
from datetime import datetime
import logging
from odoo.http import request
import json
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'
    _description = 'Products table'

    menupro_id = fields.Char(string='MenuPro ID')
    picture = fields.Char(string='Picture')
    pos_preferred_location_id = fields.Many2one(
        'stock.location',
        string="Emplacement préféré ",
        domain=[('usage', '=', 'internal')],
        help="Lors des ventes en POS, le stock sera prioritairement prélevé de cet emplacement, même si la quantité disponible est insuffisante."
    )
    margin = fields.Float(string="Marge (%)", compute="_compute_margin", store=True)
    bom_cost = fields.Float(
        string="Coût Nomenclature",
        compute='_compute_bom_cost',
        digits='Product Price',
        help="Coût calculé basé sur la nomenclature principale"
    )

    @api.depends('bom_ids.cost_per_unit')
    def _compute_bom_cost(self):
        for product in self:
            # Find the active main BoM
            main_bom = product.bom_ids.filtered(
                lambda b: b.active and b.type == 'normal' and not b.product_id
            )[:1]  # Take the first one only
            product.bom_cost = main_bom.cost_per_unit if main_bom else 0.0

    def sync_menus(self):
        """ To be triggered to synchronize menus in Odoo Menupro Restaurant and Menupro mobile """
        url = tools.config.get("synchronize_menus_endpoint")
        base_url = request.httprequest.host_url
        data = {
            'created': [],
            'updated': [],
            'deleted': []
        }
        headers = {'Content-Type': 'application/json'}
        response = requests.post(base_url + url, headers=headers, data=json.dumps(data), timeout=1200)
        return response

    def create_only_in_odoo(self, vals):
        """ This is a dedicated method to CREATE product (A.K.A. menu) ONLY in Odoo and not in MenuPro Server"""
        return super(ProductTemplate, self).create(vals)

    def write_only_in_odoo(self, vals):
        """ This is a dedicated method to UPDATE product (A.K.A. menu) ONLY in Odoo and not in MenuPro Server"""
        return super(ProductTemplate, self).write(vals)

    def create(self, vals_list):
        if isinstance(vals_list, list):
            created_records = self.env['product.template']  # recordset vide

            # Create storable products only in Odoo (not in MenuPro)
            consu_products = [val for val in vals_list if val.get('is_storable') is True]
            non_consu_products = [val for val in vals_list if val.get('is_storable') is False]

            if consu_products:
                created_records += super(ProductTemplate, self).create(consu_products)

            if non_consu_products:
                for product_vals in non_consu_products:
                    # Check if product has pos_category with menupro_id before creating in MenuPro
                    if self._should_create_in_menupro_for_create(product_vals):
                        self._process_single_product(product_vals)   # create in MenuPro and Odoo
                    else:
                        _logger.info("Skipping MenuPro creation for product %s - no valid pos_category with menupro_id", product_vals.get('name', 'Unknown'))
                # Always create in Odoo regardless of MenuPro status
                created_records += super(ProductTemplate, self).create(non_consu_products)

            return created_records

        if vals_list.get('is_storable') is True:
            # Create only in Odoo
            return super(ProductTemplate, self).create(vals_list)

        # Check if product has pos_category with menupro_id before creating in MenuPro
        if self._should_create_in_menupro_for_create(vals_list):
            # Create in both MenuPro and Odoo
            self._process_single_product(vals_list)
        else:
            _logger.info("Skipping MenuPro creation for product %s - no valid pos_category with menupro_id", vals_list.get('name', 'Unknown'))
        
        # Always create in Odoo regardless of MenuPro status
        return super(ProductTemplate, self).create(vals_list)

    def _should_create_in_menupro_for_create(self, vals):
        """ Check if product should be created in MenuPro based on pos_category menupro_id """
        # Get pos_category from vals
        pos_categ_ids = vals.get('pos_categ_ids')
        if not pos_categ_ids:
            return False
        
        # Handle both single ID and list of IDs
        if isinstance(pos_categ_ids, list):
            pos_categ_ids = pos_categ_ids[0][2] if pos_categ_ids[0][0] == 6 else [pos_categ_ids[0][1]]
        elif isinstance(pos_categ_ids, tuple):
            pos_categ_ids = [pos_categ_ids[0][1]]
        else:
            pos_categ_ids = [pos_categ_ids]
        
        categories = self.env['pos.category'].browse(pos_categ_ids).exists()
        return any(categories.mapped('menupro_id'))

    def _process_single_product(self, vals):
        """Helper method to process a single product creation."""
        api_url = tools.config.get("menu_url")
        odoo_secret_key = tools.config.get("odoo_secret_key")
        if not odoo_secret_key:
            _logger.error("odoo_secret_key missing ")

        # Create the menu in MenuPro Server
        data = self.prepare_data(vals)
        response = requests.post(api_url, json=data, headers={'x-odoo-key': odoo_secret_key})
        status_code = response.status_code
        response_data = response.json()

        # Save the associated menupro ID
        menupro_id = response.json().get('id')
        vals['menupro_id'] = menupro_id

        # Upload image if present
        # if 'image_1920' in vals and vals["image_1920"]:
        # self._upload_image_to_menupro(vals, menupro_id)
        _logger.info('\033[92mSuccessfully created menu in MenuPro\033[0m')
        return {"status_code": status_code, "response_data": response_data}

    def write(self, vals):
        res = super(ProductTemplate, self).write(vals)
        for product in self:
            _logger.debug("Updating product: %s", product.name)

            if product.is_storable is True:
                continue
            # Check if product needs to be created in MenuPro during update
            if not product.menupro_id and self._should_create_in_menupro_for_update(product):
                self._create_product_in_menupro(product)
            else:
                # Normal update flow
                self._create_or_update_menupro_menu(product)

        # If image_1920 is updated, upload the new image to S3 and update MenuPro
        # if 'image_1920' in vals and vals["image_1920"]:
        # for product in self:
        # if product.menupro_id:
        # self._upload_image_to_menupro(vals, product.menupro_id)
        _logger.info(f'\033[92mSuccessfully updated the menu with vals {vals} in MenuPro and Odoo Servers\033[0m')  # Green
        return res

    def _should_create_in_menupro_for_update(self, product):
        """ Check if product should be created in MenuPro during update (no menupro_id but has pos_category) """
        if not product.pos_categ_ids:
            return False
        # Check if any pos_category has menupro_id - Optimized to avoid N+1
        # Use any() with mapped() to check in one operation
        if any(product.pos_categ_ids.mapped('menupro_id')):
            return True
        
        _logger.debug("Product %s has pos_category but none have menupro_id - skipping MenuPro creation", product.name)
        return False

    def _create_product_in_menupro(self, product):
        """ Create product in MenuPro during update """
        try:
            api_url = tools.config.get("menu_url")
            odoo_secret_key = tools.config.get("odoo_secret_key")
            if not odoo_secret_key:
                _logger.error("odoo_secret_key missing")
                return

            # Prepare data for MenuPro
            data = self.prepare_data(product)
            _logger.debug("MenuPro data prepared for product %s", product.name)
            response = requests.post(api_url, json=data, headers={'x-odoo-key': odoo_secret_key})
            
            if response.status_code in [200, 201]:
                response_data = response.json()
                menupro_id = response_data.get('id')
                if menupro_id:
                    product.write({'menupro_id': menupro_id})
                else:
                    _logger.warning("Failed to get menupro_id from response for product %s", product.name)
            else:
                _logger.error("Failed to create product %s in MenuPro. Status: %s", product.name, response.status_code)
                
        except Exception as e:
            _logger.error("Error creating product %s in MenuPro: %s", product.name, e, exc_info=True)

    def _create_or_update_menupro_menu(self, product):
        # Get data
        data = self.prepare_data(product)
        odoo_secret_key = tools.config.get("odoo_secret_key")

        # If product is found in product.template => update (in case of creation an etiquette)
        if product.id:
            # If the menupro_id is undefined or null -> pass
            if product.menupro_id is None or product.menupro_id is False:
                return

            # Update the existing MenuPro menu
            api_url = f"{tools.config.get('menu_url')}/{product.menupro_id}"
            existing_product = self.env['product.template'].search([('id', '=', product.id)], limit=1)

            # Update category using POS category menupro_id (not product category)
            menu_categ_id = self._get_menu_categ_from_pos_categories(product.pos_categ_ids)
            if menu_categ_id:
                data['menuCateg'] = menu_categ_id

            # Call API to update menu in MenuPro
            response = requests.patch(api_url, json=data,  headers={'x-odoo-key': odoo_secret_key})
            _logger.debug("MenuPro update response - Status: %s, URL: %s", response.status_code, response.request.url)
            
            # Log detailed info only in debug mode, and mask sensitive headers
            if _logger.isEnabledFor(logging.DEBUG):
                safe_headers = {k: v if k not in ['x-odoo-key', 'x-secret-key'] else '***MASKED***' 
                               for k, v in response.request.headers.items()}
                _logger.debug("Response details - Reason: %s, Headers: %s", response.reason, safe_headers)

            if response.status_code != 200:
                return "There is a problem while updating Menupro Menu"

        # If product not found => create
        else:
            # Create a new MenuPro menu
            product = super(ProductTemplate, self).create(product)
            api_url = tools.config.get("create_menu_url")
            data = self.prepare_data(product)
            response = requests.post(api_url, json=data, headers={'x-odoo-key': odoo_secret_key})
            if response.status_code == 200:
                menupro_id = response.json().get('id')
                product.write({'menupro_id': menupro_id})

    def _upload_image_to_menupro(self, vals, menupro_id):
        try:
            # Decode the image and extract the type
            image_data = self.decode_image(vals['image_1920'])
            image_type = image_data[1]
            image_decoded = image_data[0]

            # Get signed url
            response_image = self.get_s3_signed_url(f'menu_image.{image_type}', menupro_id)

            # Get from conf
            store_picture_url = tools.config.get('store_picture_url')
            odoo_secret_key = tools.config.get("odoo_secret_key")

            # Upload to S3
            self.upload_image_to_s3(image_decoded, image_type, response_image['signedurl'], odoo_secret_key )

            # Store picture key
            data = {'menu_id': menupro_id, 'picture': response_image['key']}

            response_store = requests.post(store_picture_url, json=data,  headers={'x-odoo-key': odoo_secret_key})
            response_store.raise_for_status()
            _logger.info(f"\033[94mPicture uploaded successfully {response_image['key']}\033[0m")  # Green

            base_s3_url = tools.config.get('base_s3_url')
            if base_s3_url:
                vals['picture'] = f"{base_s3_url}/{response_image['key']}"
            else:
                _logger.error('There is no base_s3_url in Config')
                raise UserError("There is no base_s3_url in Config")
        except Exception as e:
            _logger.error(f"Error processing image: {e}")
            raise UserError(f"Error processing image: {e}")

    def unlink(self):
        """ Delete menu from MenuPro server AND Odoo database """
        api_url = tools.config.get("delete_menu_url")
        odoo_secret_key = tools.config.get("odoo_secret_key")

        for product in self:
            if product.menupro_id:
                menupro_id = product.menupro_id
                url = f"{api_url}/{menupro_id}"
                requests.delete(url, headers={'x-odoo-key': odoo_secret_key})

        # Call the parent unlink method to delete the product in Odoo
        _logger.info("Product deleted in Menupro Server and Odoo")
        return super(ProductTemplate, self).unlink()

    def prepare_data(self, product):
        if isinstance(product, dict):
            list_price = product.get('list_price', 0.0)
            name = product.get('name', '')
            description = product.get('description', '') or ''
            pos_categ_ids = product.get('pos_categ_ids', [])
            self_order_available = product.get('self_order_available', True)
        else:
            list_price = getattr(product, 'list_price', 0.0)
            name = getattr(product, 'name', '')
            description = getattr(product, 'description', '') or ''
            pos_categ_ids = getattr(product, 'pos_categ_ids', [])
            self_order_available = getattr(product, 'self_order_available', True)
        api_url = tools.config.get("api_url")
        if api_url is None:
            _logger.error("There is no API_URL in Config")
            return {}

        restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
        if restaurant_id is None:
            _logger.error("There is no restaurant ID in Config")
            return {}

        secret_key = tools.config.get("secret_key")
        if secret_key is None:
            _logger.error("There is no secret_key in Config")
            return {}

        try:
            response = requests.get(api_url + restaurant_id, headers={'x-secret-key': secret_key})
            if response.status_code == 200:
                restaurant = response.json()
                name_restaurant = restaurant.get('name')

                data = {
                    'title': name,
                    'price': list_price,
                    'description': description,
                    'restaurantId': restaurant_id,
                    'restaurantName': name_restaurant,
                    'synchronizeOdoo': datetime.today().isoformat()
                }

                # Add menuCateg from first POS category with menupro_id (not product category)
                menu_categ_id = self._get_menu_categ_from_pos_categories(pos_categ_ids)
                if menu_categ_id:
                    data['menuCateg'] = menu_categ_id

                if self_order_available is False:
                    data['status'] = 'BLOCKED'
                else:
                    data['status'] = 'PUBLISHED'
                
                _logger.debug("Prepared MenuPro data for product: %s", data.get('title'))
                return data
            else:
                _logger.error("There is a problem while getting restaurant Info")
                return {}
        except Exception as e:
            _logger.error(f"Error preparing data: {e}")
            return {}

    def _get_menu_categ_from_pos_categories(self, pos_categ_ids):
        """Get menupro_id from first POS category that has menupro_id"""
        if not pos_categ_ids:
            return None

        # Convert pos_categ_ids to a list of IDs
        category_ids = []

        # Handle different pos_categ_ids formats
        if isinstance(pos_categ_ids, list) and pos_categ_ids:
            if isinstance(pos_categ_ids[0], tuple):
                if pos_categ_ids[0][0] == 6:  # Replace operation (6, 0, [ids])
                    category_ids = pos_categ_ids[0][2] if pos_categ_ids[0][2] else []
                elif pos_categ_ids[0][0] == 4:  # Link operation (4, id, 0)
                    category_ids = [pos_categ_ids[0][1]]
                elif pos_categ_ids[0][0] == 3:  # Unlink operation (3, id, 0)
                    category_ids = []
            else:
                # Already a list of IDs
                category_ids = pos_categ_ids
        elif isinstance(pos_categ_ids, tuple):
            if pos_categ_ids[0] == 6:
                category_ids = pos_categ_ids[2] if pos_categ_ids[2] else []
            elif pos_categ_ids[0] == 4:
                category_ids = [pos_categ_ids[1]]
        # If pos_categ_ids is a recordset
        elif hasattr(pos_categ_ids, '_name') and pos_categ_ids._name == 'pos.category':
            category_ids = pos_categ_ids.ids
        else:
            # Try to use it as a single ID
            try:
                category_ids = [int(pos_categ_ids)]
            except (ValueError, TypeError):
                return None

        # Find first POS category with menupro_id - Optimized to avoid N+1
        # Browse all categories at once instead of one by one
        try:
            categories = self.env['pos.category'].browse([int(cid) for cid in category_ids]).exists()
            for pos_category in categories:
                if pos_category.menupro_id:
                    _logger.debug("Using menuCateg from POS category '%s' with menupro_id: %s", 
                                 pos_category.name, pos_category.menupro_id)
                    return pos_category.menupro_id
        except Exception as e:
            _logger.error(f"Error processing pos_category IDs: {e}")

        return None
    def get_s3_signed_url(self, image, id_menu):
        get_signedurl_url = tools.config.get('get_signedurl_menu_url') + '?menuPicName=' + image + '&idMenu=' + id_menu
        if not get_signedurl_url:
            raise UserError("There is no signed url in Config")

        # Replace with your actual API endpoint and parameters
        response = requests.get(get_signedurl_url)
        response.raise_for_status()
        return response.json()

    def upload_image_to_s3(self, image_data, image_type, signed_url, odoo_secret_key):
        headers = {'Content-Type': f'image/{image_type}', 'x-odoo-key': odoo_secret_key}
        response = requests.put(signed_url, data=image_data, headers=headers)
        response.raise_for_status()
        return response

    def decode_image(self, image_data):
        import imghdr
        # Ensure image_data is in binary format if not already
        if isinstance(image_data, str):
            import base64
            image_data = base64.b64decode(image_data)

        # Determine the image type dynamically
        image_type = imghdr.what(None, h=image_data)
        if not image_type:
            # Handle the case where the image type cannot be determined
            raise ValueError("Could not determine image type")

        return image_data, image_type

    @api.depends('list_price', 'standard_price')
    def _compute_margin(self):
        for product in self:
            if product.type == 'consu' and product.list_price:
                product.margin = ((product.list_price - product.standard_price) / product.list_price)
            else:
                product.margin = False