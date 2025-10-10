from odoo.http import request
import json
import requests
from odoo import http, tools
from odoo.exceptions import UserError
import logging
from ..utils import image_utils  # To access get_image_as_base64

_logger = logging.getLogger(__name__)


class MenuSyncController(http.Controller):
    @http.route('/sync_menus', type='json', auth='public', methods=['POST'])
    def sync_menus(self):
        """
            Endpoint to synchronize all menus from an external API.
            This is for restaurants having <80 menus
        """
        try:
            config_params = self._validate_config()
            _logger.info('\033[94m======================== GETTING RESTAURANT MENUS ========================\033[0m')

            # ✅ Récupérer les menus
            menus = self._fetch_menus(
                config_params['restaurant_id'],
                config_params['synchronize_menus_url'],
                config_params['odoo_secret_key']
            )


            if isinstance(menus, str):
                _logger.error(f"❌ Erreur: menus est une string au lieu d'un dict: {menus}")
                return {'status': 'error', 'message': 'Failed to fetch menus'}

            if not isinstance(menus, dict):
                _logger.error(f"❌ Erreur: menus n'est pas un dict: {type(menus)}")
                return {'status': 'error', 'message': 'Invalid menus format'}

            created_count = len(menus.get('created', []))
            updated_count = len(menus.get('updated', []))
            deleted_count = len(menus.get('deleted', []))



            # ✅ Vérifier si des menus existent
            if created_count == 0 and updated_count == 0 and deleted_count == 0:
                _logger.warning("⚠️ Aucun menu à synchroniser (created=0, updated=0, deleted=0)")
            else:
                # ✅ Traiter les menus avec le contexte
                self._process_menus(menus, config_params['base_s3_url'])

            _logger.info(
                '\033[94m======================== FINISH GETTING RESTAURANT MENUS ========================\033[0m')
            return {
                'status': 'success',
                'message': f'Menus synchronized - Created: {created_count}, Updated: {updated_count}, Deleted: {deleted_count}'
            }

        except Exception as e:
            _logger.error("Error while synchronizing menus: %s", str(e), exc_info=True)
            return {'status': 'error', 'message': str(e)}

    @http.route('/sync_menus_by_range', type='json', auth='public', methods=['POST'])
    def sync_menus_by_range(self):
        """
            Endpoint to synchronize menus by range from an external API.
            This is for restaurants having >80 menus
        """
        try:
            config_params = self._validate_config()
            _logger.info(
                '\033[94m======================== GETTING RESTAURANT MENUS ========================\033[0m')  # Blue

            menus = self._fetch_menus_by_range(config_params['restaurant_id'], config_params['synchronize_menus_url'], config_params['odoo_secret_key'])
            self._process_menus(menus, config_params['base_s3_url'])

            _logger.info(
                '\033[94m======================== FINISH GETTING RESTAURANT MENUS ========================\033[0m')  # Blue
            return {'status': 'success', 'message': 'Menus synchronized successfully'}

        except Exception as e:
            _logger.error("Error while synchronizing menus by range: %s", str(e), exc_info=True)
            return {'status': 'error', 'message': str(e)}

    # Helper methods

    @staticmethod
    def _validate_config():
        """Validate required configuration parameters."""
        config_params = {
            'synchronize_menus_url': tools.config.get('synchronize_menus_url'),
            'base_s3_url': tools.config.get('base_s3_url'),
            'secret_key': tools.config.get('secret_key'),
            'restaurant_id': request.env['ir.config_parameter'].sudo().get_param('restaurant_id'),
            'odoo_secret_key': tools.config.get('odoo_secret_key')
        }

        for key, value in config_params.items():
            if not value:
                _logger.error(f"❌ {key} is not valid in Config")
                raise UserError(f"There is no {key} in Config")

        _logger.info('✅ Configuration keys are validated')
        return config_params

    @staticmethod
    def _fetch_menus(restaurant_id, synchronize_menus_url, odoo_secret_key):
        """Fetch menus from the external API."""
        try:
            _logger.info(f"🔍 Fetching menus from: {synchronize_menus_url}{restaurant_id}")

            response = requests.get(
                f"{synchronize_menus_url}{restaurant_id}",
                headers={'x-odoo-key': odoo_secret_key},
                timeout=30
            )

            _logger.info(f"📡 Response status: {response.status_code}")

            if response.status_code != 200:
                error_msg = f'Failed to fetch menus. Status: {response.status_code}, Response: {response.text}'
                _logger.error(f'❌ {error_msg}')
                # ✅ RETOURNER UN DICT, PAS UNE STRING
                return {'created': [], 'updated': [], 'deleted': [], 'error': error_msg}

            menus = response.json()
            _logger.info(f"📦 Response JSON: {response.text}")

            _logger.info(f"✅ Menus récupérés avec succès: {type(menus)}")

            # ✅ Vérifier la structure
            if not isinstance(menus, dict):
                _logger.error(f"❌ Format invalide: attendu dict, reçu {type(menus)}")
                return {'created': [], 'updated': [], 'deleted': []}

            return menus

        except requests.exceptions.Timeout:
            _logger.error("❌ Timeout lors de la récupération des menus")
            return {'created': [], 'updated': [], 'deleted': []}
        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Erreur réseau: {e}")
            return {'created': [], 'updated': [], 'deleted': []}
        except Exception as e:
            _logger.error(f"❌ Erreur inattendue: {e}", exc_info=True)
            return {'created': [], 'updated': [], 'deleted': []}

    @staticmethod
    def _fetch_menus_by_range(restaurant_id, synchronize_menus_url, odoo_secret_key):
        """Fetch menus from the external API."""
        data = json.loads(request.httprequest.data)
        skip = data['skip']
        limit = data['limit']
        response = requests.get(synchronize_menus_url + restaurant_id + '/' + str(limit) + '/' + str(skip), headers={'x-odoo-key': odoo_secret_key})

        if response.status_code != 200:
            error_msg = {'error': 'Failed to fetch menus from the external API'}
            result = dict(
                success=False,
                message=http.Response(json.dumps(error_msg), content_type='application/json'),
            )
            return json.dumps(result)

        return response.json()

    def _process_menus(self, menus, s3_base_url):
        """Process the fetched menus."""
        _logger.info("🔄 Début du traitement des menus")

        # ✅ Ajouter le contexte pour éviter la boucle
        pos_menus_model = http.request.env['product.template'].sudo().with_context(
            from_menupro_sync=True
        )
        product_category_model = http.request.env['product.category'].sudo()
        pos_category_model = http.request.env['pos.category'].sudo()
        account_tax = http.request.env['account.tax'].sudo().search([('amount', '=', 0.000)])

        created_menus = menus.get('created', [])
        updated_menus = menus.get('updated', [])
        deleted_menus = menus.get('deleted', [])

        for i, menu_data in enumerate(created_menus, 1):
            try:
                _logger.info(f"  ➕ Création menu {i}/{len(created_menus)}: {menu_data.get('title', 'N/A')}")
                self._create_menu(menu_data, pos_menus_model, product_category_model, pos_category_model, account_tax,
                                  s3_base_url)
            except Exception as e:
                _logger.error(f"  ❌ Erreur création menu {i}: {e}", exc_info=True)

        for i, menu_data in enumerate(updated_menus, 1):
            try:
                _logger.info(f"  🔄 MAJ menu {i}/{len(updated_menus)}: {menu_data.get('title', 'N/A')}")
                self._update_menu(menu_data, pos_menus_model, product_category_model, pos_category_model, account_tax,
                                  s3_base_url)
            except Exception as e:
                _logger.error(f"  ❌ Erreur MAJ menu {i}: {e}", exc_info=True)

        for i, menu_id in enumerate(deleted_menus, 1):
            try:
                _logger.info(f"  ➖ Suppression menu {i}/{len(deleted_menus)}: {menu_id}")
                self._deactivate_menu(menu_id, pos_menus_model)
            except Exception as e:
                _logger.error(f"  ❌ Erreur suppression menu {i}: {e}", exc_info=True)

        _logger.info("✅ Fin du traitement des menus")

    def _create_menu(self, menu_data, pos_menus_model, product_category_model, pos_category_model, account_tax, s3_base_url):
        """Create a new menu."""
        existing_menu = pos_menus_model.search([('menupro_id', '=', menu_data['_id'])], limit=1)
        if existing_menu:
            # If the menu exists already then update it
            self._update_menu(menu_data, pos_menus_model, product_category_model, pos_category_model, account_tax, s3_base_url)
        else:
            menu_obj = self._prepare_menu_obj(menu_data, s3_base_url)
            menu_obj.update({
                'menupro_id': menu_data['_id'],
                'available_in_pos': True,
                'taxes_id': [(6, 0, account_tax.ids)],
            })
            if 'menuCateg' in menu_data and menu_data['menuCateg']:
                self._update_menu_category(menu_obj, menu_data, product_category_model, pos_category_model, s3_base_url)

            created_menu = pos_menus_model.create_only_in_odoo(menu_obj)

            # Update the category in which the menu will be filtered in POS interface
            self._update_pos_categories(created_menu, menu_data, pos_category_model)

    def _update_menu(self, menu_data, pos_menus_model, product_category_model, pos_category_model, account_tax, s3_base_url):
        """Update an existing menu."""
        menu = pos_menus_model.search([('menupro_id', '=', menu_data['_id'])], limit=1)
        if menu:
            menu_obj = self._prepare_menu_obj(menu_data, s3_base_url)
            menu.write_only_in_odoo(menu_obj)

            if 'menuCateg' in menu_data and menu_data['menuCateg']:
                self._update_menu_category(menu_obj, menu_data, product_category_model, pos_category_model, s3_base_url)
                menu.write_only_in_odoo(menu_obj)
        else:
            self._create_menu(menu_data, pos_menus_model, product_category_model, pos_category_model, account_tax, s3_base_url)

    @staticmethod
    def _deactivate_menu(menu_id, pos_menus_model):
        """Deactivate a deleted menu."""
        menu = pos_menus_model.search([('menupro_id', '=', menu_id)])
        if menu:
            menu.write_only_in_odoo({'available_in_pos': False})

    @staticmethod
    def _prepare_menu_obj(menu_data, s3_base_url):
        """Prepare a menu object for creation or update."""
        picture = image_utils.get_image_as_base64(s3_base_url + menu_data['picture']) if 'picture' in menu_data and menu_data[
            'picture'] else None
        picture_url = s3_base_url + menu_data['picture'] if 'picture' in menu_data and menu_data['picture'] else None

        return {
            'name': menu_data['title'],
            'list_price': menu_data['price'],
            'picture': picture_url,
            'image_1920': picture
        }

    @staticmethod
    def _update_menu_category(menu_obj, menu_data, product_category_model, pos_category_model, s3_base_url):
        """Update or create a menu category."""
        category_data = menu_data['menuCateg']
        product_category = product_category_model.search([('menupro_id', '=', category_data['_id'])])
        pos_category = pos_category_model.search([('menupro_id', '=', category_data['_id'])])

        category_picture = image_utils.get_image_as_base64(
            s3_base_url + category_data['picture']) if 'picture' in category_data and category_data[
            'picture'] else None
        category_picture_url = s3_base_url + category_data[
            'picture'] if 'picture' in category_data and category_data['picture'] else None

        # This is the category of product
        if not product_category:
            category_obj = {
                'menupro_id': category_data['_id'],
                'name': category_data['menuProName'],
                'type_name': category_data['typeName'],
                'picture': category_picture_url,
            }
            product_category = product_category_model.create(category_obj)

        # This is the category in which the product will be FILTERED in POS
        if not pos_category:
            category_obj = {
                'menupro_id': category_data['_id'],
                'name': category_data['menuProName'],
                'type_name': category_data['typeName'],
                'picture': category_picture_url,
                'image_128': category_picture,
                'option_name': category_data['_id']
            }
            pos_category = pos_category_model.create(category_obj)

        menu_obj['categ_id'] = product_category.id

        # Overwrite the pos_category (only 1 category)
        menu_obj['pos_categ_ids'] = [(5, 0, 0)]  # This will remove all existing relations
        menu_obj['pos_categ_ids'].append((4, pos_category.id))  # Add the new category

    @staticmethod
    def _update_pos_categories(menu, menu_data, pos_category_model):
        """Update POS categories for a menu."""
        if 'menuCateg' in menu_data and menu_data['menuCateg']:
            pos_category = pos_category_model.search([('menupro_id', '=', menu_data['menuCateg']['_id'])])
            if pos_category:
                menu.write({
                    'pos_categ_ids': [(4, id) for id in pos_category.ids + menu.pos_categ_ids.ids],
                })
