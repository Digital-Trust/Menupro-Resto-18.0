import json
import logging
from odoo import http, fields
from odoo.http import request
from odoo.addons.pos_self_order.controllers.orders import PosSelfOrderController
import uuid
from datetime import date, datetime

_logger = logging.getLogger(__name__)

def json_default(obj):
    """Fonction de sérialisation personnalisée pour les objets non standards"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return obj.decode('utf-8')
    raise TypeError(f"Type {type(obj)} not serializable")


def same_attributes(line_attrs, incoming_attrs):
    """Compare les attributs d'une ligne existante avec les attributs entrants"""
    return set(line_attrs.ids) == set(incoming_attrs or [])


class OrderController(PosSelfOrderController):

    def get_restaurant_discount_config(self, restaurant_id=None, discount_code=None):
        """
        Récupère la configuration de remise pour un restaurant et code spécifiques

        :param restaurant_id: ID du restaurant
        :param discount_code: Code de remise
        :return: dict avec la configuration de remise
        """
        config_model = request.env['restaurant.discount.config'].sudo()
        return config_model.get_config_for_code(restaurant_id, discount_code)

    def apply_qr_mobile_discount(self, amount_total, restaurant_id=None, discount_code=None):
        """
        Applique une remise QR mobile selon le restaurant et le code de remise

        :param amount_total: Montant total de la commande
        :param restaurant_id: ID du restaurant
        :param discount_code: Code de remise
        :return: dict avec les détails de la remise ou None si pas applicable
        """
        discount_config = self.get_restaurant_discount_config(restaurant_id, discount_code)

        if not discount_config['enabled']:
            return None
        if amount_total < discount_config['min_amount']:
            return None

        discount_percentage = discount_config['discount_percentage']
        discount_amount = amount_total * (discount_percentage / 100)

        # Appliquer le plafond si défini
        if discount_config['max_discount'] and discount_amount > discount_config['max_discount']:
            discount_amount = discount_config['max_discount']
            effective_percentage = (discount_amount / amount_total) * 100
        else:
            effective_percentage = discount_percentage

        new_total = amount_total - discount_amount

        return {
            'discount_amount': discount_amount,
            'new_total': new_total,
            'discount_percentage': effective_percentage,
            'original_percentage': discount_percentage,
            'discount_name': discount_config['discount_name'],
            'min_amount': discount_config['min_amount'],
            'max_discount': discount_config['max_discount'],
            'capped': discount_config['max_discount'] and discount_amount >= discount_config['max_discount']
        }

    def apply_default_mobile_promo(self, amount_total, restaurant_id=None):
        """
        Applique automatiquement le code promo par défaut pour mobile self-order

        :param amount_total: Montant total de la commande
        :param restaurant_id: ID du restaurant
        :return: dict avec les détails de la remise ou None si pas applicable
        """
        config_model = request.env['restaurant.discount.config'].sudo()
        discount_config = config_model.get_default_mobile_promo_config(restaurant_id)

        if not discount_config['enabled']:
            return None
        if amount_total < discount_config['min_amount']:
            return None

        discount_percentage = discount_config['discount_percentage']
        discount_amount = amount_total * (discount_percentage / 100)

        # Appliquer le plafond si défini
        if discount_config['max_discount'] and discount_amount > discount_config['max_discount']:
            discount_amount = discount_config['max_discount']
            effective_percentage = (discount_amount / amount_total) * 100
        else:
            effective_percentage = discount_percentage

        new_total = amount_total - discount_amount

        return {
            'discount_amount': discount_amount,
            'new_total': new_total,
            'discount_percentage': effective_percentage,
            'original_percentage': discount_percentage,
            'discount_name': discount_config['discount_name'],
            'min_amount': discount_config['min_amount'],
            'max_discount': discount_config['max_discount'],
            'capped': discount_config['max_discount'] and discount_amount >= discount_config['max_discount']
        }

    def get_or_create_discount_product(self, discount_name):
        """
        Récupère ou crée un produit de remise

        :param discount_name: Nom du produit de remise
        :return: Produit de remise
        """
        discount_product = request.env['product.product'].sudo().search([
            ('name', '=', discount_name),
            ('type', '=', 'service')
        ], limit=1)

        if not discount_product:
            discount_product = request.env['product.product'].sudo().create({
                'name': discount_name,
                'type': 'service',
                'categ_id': request.env.ref('product.product_category_all').id,
                'list_price': 0.0,
                'sale_ok': True,
                'purchase_ok': False,
            })
        return discount_product

    def calculate_total_before_discount(self, existing_order, discount_product_name=None):
        """
        Calcule le total avant remise en excluant les lignes de remise existantes

        :param existing_order: Commande existante
        :param discount_product_name: Nom du produit de remise à exclure
        :return: Total avant remise
        """
        total = 0.0
        if existing_order:
            for line in existing_order.lines:
                if discount_product_name and line.product_id.name == discount_product_name:
                    continue
                total += line.price_subtotal_incl
        return total

    def find_existing_line(self, existing_order, product_id, note, attribute_value_ids):
        """
        Trouve une ligne existante avec les mêmes caractéristiques

        :param existing_order: Commande existante
        :param product_id: ID du produit
        :param note: Note de la ligne
        :param attribute_value_ids: IDs des attributs
        :return: Ligne existante ou None
        """
        if not existing_order:
            return None

        for line in existing_order.lines:
            if (line.product_id.id == product_id and
                    (line.note or '') == (note or '') and
                    same_attributes(line.attribute_value_ids, attribute_value_ids)):
                return line
        return None

    def process_order_lines(self, order_data, pos_config, existing_order=None):
        """
        Traite les lignes de commande et calcule les totaux

        :param order_data: Données de la commande
        :param pos_config: Configuration POS
        :param existing_order: Commande existante (optionnel)
        :return: tuple (line_operations, total_before_discount)
        """
        line_operations = []
        total_before_discount = 0.0

        for line in order_data['lines']:
            product = request.env['product.product'].sudo().search([
                ('menupro_id', '=', line.get('menupro_id'))
            ], limit=1)

            if not product:
                continue

            # Récupération des données de la ligne
            qty = line.get('qty', 1)
            note = line.get('note', '')
            attribute_value_ids = line.get('attribute_value_ids', [])
            custom_attribute_value_ids = line.get('custom_attribute_value_ids', [])
            price_extra = line.get('price_extra', 0.0)
            price_unit = product.lst_price + price_extra

            # Calcul des taxes
            taxes_res = product.taxes_id.compute_all(
                price_unit,
                currency=pos_config.pricelist_id.currency_id,
                quantity=qty,
                product=product
            )
            total_before_discount += taxes_res['total_included']

            # Génération des données communes
            line_uuid = str(uuid.uuid4())
            attribute_value_ids_clean = [aid for aid in attribute_value_ids if
                                         request.env['product.template.attribute.value'].sudo().browse(aid).exists()]
            attribute_names = request.env['product.template.attribute.value'].sudo().browse(
                attribute_value_ids_clean).mapped('name')
            full_product_name = f"{product.name} ({', '.join(attribute_names)})" if attribute_names else product.name

            # Données de base de la ligne
            base_line_data = {
                'product_id': product.id,
                'qty': qty,
                'note': note,
                'price_unit': price_unit,
                'price_subtotal': taxes_res['total_excluded'],
                'price_subtotal_incl': taxes_res['total_included'],
                'tax_ids': [(6, 0, product.taxes_id.ids)],
                'uuid': line_uuid,
                'attribute_value_ids': [(6, 0, attribute_value_ids)],
                'custom_attribute_value_ids': [(6, 0, custom_attribute_value_ids)],
                'price_extra': price_extra,
                'full_product_name': full_product_name,
            }

            # Gestion des lignes existantes vs nouvelles
            existing_line = self.find_existing_line(existing_order, product.id, note, attribute_value_ids)

            if existing_line:
                # Mise à jour de la quantité existante
                new_qty = existing_line.qty + qty
                updated_taxes = existing_line.tax_ids.compute_all(
                    existing_line.price_unit,
                    currency=pos_config.currency_id,
                    quantity=new_qty,
                    product=existing_line.product_id,
                )

                line_operations.append((1, existing_line.id, {
                    'qty': new_qty,
                    'price_subtotal': updated_taxes['total_excluded'],
                    'price_subtotal_incl': updated_taxes['total_included'],
                }))
            else:
                # Nouvelle ligne
                line_operations.append((0, 0, base_line_data))

        return line_operations, total_before_discount

    def process_discount_line(self, discount_info, existing_order, discount_code):
        """
        Traite la ligne de remise (création ou mise à jour)

        :param discount_info: Informations de remise
        :param existing_order: Commande existante
        :param discount_code: Code de remise
        :return: Opération de ligne de remise
        """
        discount_product = self.get_or_create_discount_product(discount_info['discount_name'])

        # Recherche d'une ligne de remise existante
        existing_discount_line = None
        if existing_order:
            for line in existing_order.lines:
                if line.product_id.id == discount_product.id:
                    existing_discount_line = line
                    break

        # Création de la note de remise
        if discount_code == 'MOBILE_DEFAULT':
            discount_note = f'Remise Mobile Self-Order {discount_info["discount_percentage"]:.1f}% (Automatique)'
        else:
            discount_note = f'Remise QR mobile {discount_info["discount_percentage"]:.1f}% (Code: {discount_code})'
        if discount_info.get('capped'):
            discount_note += f' (plafonnée à {discount_info["max_discount"]}€)'

        if existing_discount_line:
            # Mise à jour de la ligne existante
            return (1, existing_discount_line.id, {
                'price_unit': -discount_info['discount_amount'],
                'price_subtotal': -discount_info['discount_amount'],
                'price_subtotal_incl': -discount_info['discount_amount'],
                'note': discount_note,
            })
        else:
            # Création d'une nouvelle ligne
            return (0, 0, {
                'product_id': discount_product.id,
                'qty': 1,
                'note': discount_note,
                'price_unit': -discount_info['discount_amount'],
                'price_subtotal': -discount_info['discount_amount'],
                'price_subtotal_incl': -discount_info['discount_amount'],
                'tax_ids': [(6, 0, [])],
                'uuid': str(uuid.uuid4()),
                'attribute_value_ids': [(6, 0, [])],
                'custom_attribute_value_ids': [(6, 0, [])],
                'price_extra': 0.0,
                'full_product_name': discount_product.name,
            })

    def update_existing_order(self, existing_order, line_operations, access_token, takeaway, menupro_id,
                              mobile_user_id=None, subscription_id=None, paid_online=None):
        """
        Met à jour une commande existante avec gestion takeaway/floating orders
        """
        # Application des opérations sur les lignes
        for op in line_operations:
            if op[0] == 1:
                request.env['pos.order.line'].sudo().browse(op[1]).write(op[2])

        # Ajout des nouvelles lignes
        new_lines = [op for op in line_operations if op[0] == 0]
        if new_lines:
            existing_order.write({'lines': new_lines})

        # *** GESTION DES MISES À JOUR ***
        update_values = {}
        if mobile_user_id is not None:
            update_values['mobile_user_id'] = mobile_user_id
        if subscription_id is not None:
            update_values['subscription_id'] = subscription_id
        if paid_online is not None:
            update_values['paid_online'] = paid_online
            _logger.info(f"Mise à jour paid_online: {paid_online}")
        # Gestion du changement takeaway
        if takeaway != existing_order.takeaway:
            update_values['takeaway'] = takeaway

            if takeaway:
                # Conversion vers floating order
                update_values['table_id'] = False
                update_values['floating_order_name'] = f"Takeaway {existing_order.name}"
                _logger.info(f"Conversion de la commande {existing_order.name} vers floating order (takeaway)")
            else:
                # Conversion de takeaway vers dine-in
                if not existing_order.table_id:
                    _logger.warning(f"Conversion floating order {existing_order.name} vers dine-in - table requise")
                update_values['floating_order_name'] = False  # Supprimer le nom floating

        # Mise à jour de la commande
        if update_values:
            existing_order.write(update_values)

        # Recalcul des totaux
        existing_order._onchange_amount_all()

        # Synchronisation avec données complètes
        order_data_for_sync = {
            'id': existing_order.id,
            'name': existing_order.name,
            'pos_reference': existing_order.pos_reference,
            'session_id': existing_order.session_id.id,
            'date_order': fields.Datetime.to_string(existing_order.date_order),
            'access_token': access_token,
            'amount_total': existing_order.amount_total,
            'amount_tax': existing_order.amount_tax,
            'amount_paid': existing_order.amount_paid,
            'amount_return': existing_order.amount_return,
            'uuid': existing_order.uuid,
            'table_id': existing_order.table_id.id if existing_order.table_id else False,
            'state': 'draft',
            'takeaway': takeaway,
            'sequence_number': existing_order.sequence_number,
            'mobile_user_id': mobile_user_id,
            'subscription_id': subscription_id,
            'floating_order_name': existing_order.floating_order_name,
            'paid_online': paid_online,
            'lines': [[
                1 if line.id else 0,
                line.id if line.id else 0,
                {
                    'product_id': line.product_id.id,
                    'qty': line.qty,
                    'price_unit': line.price_unit,
                    'price_subtotal': line.price_subtotal,
                    'price_subtotal_incl': line.price_subtotal_incl,
                    'tax_ids': line.tax_ids.ids,
                    'note': line.note or '',
                    'uuid': line.uuid,
                    'attribute_value_ids': line.attribute_value_ids.ids,
                    'custom_attribute_value_ids': line.custom_attribute_value_ids.ids,
                }
            ] for line in existing_order.lines]
        }

        request.env['pos.order'].sudo().sync_from_ui([order_data_for_sync])
        return existing_order

    def debug_order_fields(self, order):
        """
        Méthode pour déboguer les champs de la commande
        """
        _logger.info(f"=== DEBUG ORDER FIELDS ===")
        _logger.info(f"Order ID: {order.id}")
        _logger.info(f"mobile_user_id: {getattr(order, 'mobile_user_id', 'FIELD_NOT_EXISTS')}")
        _logger.info(f"subscription_id: {getattr(order, 'subscription_id', 'FIELD_NOT_EXISTS')}")
        _logger.info(f"table_id: {order.table_id.id}")
        _logger.info(f"state: {order.state}")
        _logger.info(f"=== END DEBUG ===")

    def create_new_order(self, pos_config, restaurant_table, line_operations, access_token, takeaway, menupro_id,
                         mobile_user_id=None, subscription_id=None, paid_online=None, menupro_name=None):
        """
        Crée une nouvelle commande avec gestion des floatingOrder pour takeaway
        """
        sequence = request.env['ir.sequence'].sudo().next_by_code('pos.order')
        amount_total = sum(line[2]['price_subtotal_incl'] for line in line_operations)
        amount_tax = sum(line[2]['price_subtotal_incl'] - line[2]['price_subtotal'] for line in line_operations)

        # Configuration de base de la commande
        order_dict = {
            'name': sequence,
            'pos_reference': sequence,
            'session_id': pos_config.current_session_id.id,
            'date_order': fields.Datetime.now().isoformat(),
            'lines': line_operations,
            'access_token': access_token,
            'amount_total': amount_total,
            'amount_tax': amount_tax,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'uuid': str(uuid.uuid4()),
            'state': 'draft',
            'sequence_number': None,
            'mobile_user_id': mobile_user_id,
            'subscription_id': subscription_id,
            'menupro_id': menupro_id,
            'paid_online': paid_online or False,
        }

        # *** GESTION TAKEAWAY - FLOATING ORDER ***
        if takeaway:
            # Pour takeaway, créer une floating order (sans table)
            # Utiliser le nom du client s'il est fourni, sinon utiliser le format par défaut
            floating_name = menupro_name if menupro_name else f"TKO-{sequence}"
            order_dict.update({
                'table_id': False,
                'takeaway': True,
                'floating_order_name': floating_name,
            })
            _logger.info(f"Création d'une floating order takeaway: {floating_name}")
        else:
            # Pour dine-in, utiliser la table normale
            order_dict.update({
                'table_id': restaurant_table.id,
                'takeaway': False,
            })
            _logger.info(f"Création d'une commande table: {restaurant_table.table_number}")

        # *** DEBUG : Log des valeurs avant création ***
        _logger.info(f"=== CREATE ORDER DEBUG ===")
        _logger.info(f"mobile_user_id à créer: {mobile_user_id}")
        _logger.info(f"subscription_id à créer: {subscription_id}")
        _logger.info(f"menupro_id à créer: {menupro_id}")
        _logger.info(f"takeaway: {takeaway}")
        _logger.info(f"paid_online: {paid_online}")
        _logger.info(f"menupro_name: {menupro_name}")
        _logger.info(f"table_id: {order_dict.get('table_id', 'None (Floating Order)')}")
        _logger.info(f"floating_order_name: {order_dict.get('floating_order_name', 'None')}")
        _logger.info(f"=== END CREATE DEBUG ===")

        # Pour les floating orders, pas besoin de table_identifier
        table_identifier = restaurant_table.identifier if restaurant_table else None
        return super().process_order_args(order_dict, access_token, table_identifier, 'mobile')

    def build_response_data(self, order, restaurant_id, discount_info=None, total_before_discount=0.0, is_update=False,
                            mobile_user_id=None, subscription_id=None):
        """
        Construit les données de réponse

        :param order: Commande (existante ou nouvelle)
        :param restaurant_id: ID du restaurant
        :param discount_info: Informations de remise
        :param total_before_discount: Total avant remise
        :param is_update: True si c'est une mise à jour
        :param mobile_user_id: ID de l'utilisateur mobile
        :param subscription_id: subscription ID de l'utilisateur mobile Pour Notif
        :return: Données de réponse
        """
        if is_update:
            response_data = {
                "success": True,
                "order_id": order.id,
                "message": "Order updated successfully",
                "restaurant_id": restaurant_id,
                'mobile_user_id': mobile_user_id,
                'subscription_id': subscription_id,
            }
            final_total = order.amount_total
        else:
            response_data = order if isinstance(order, dict) else {"success": True}
            if "restaurant_id" not in response_data:
                response_data["restaurant_id"] = restaurant_id
            final_total = response_data.get("amount_total", 0.0)



        # Ajout des informations de remise si applicable
        if discount_info:
            response_data["discount_applied"] = {
                "discount_name": discount_info["discount_name"],
                "discount_percentage": discount_info["discount_percentage"],
                "original_percentage": discount_info["original_percentage"],
                "discount_amount": discount_info["discount_amount"],
                "original_total": total_before_discount,
                "final_total": final_total,
                "capped": discount_info.get("capped", False),
                "max_discount": discount_info.get("max_discount"),
                "min_amount": discount_info.get("min_amount")
            }

        return response_data

    @http.route('/new_order', type='http', auth='public', methods=['POST'], csrf=False)
    def process_mobile_order(self, **kwargs):
        """
        Version complète avec gestion takeaway/floating orders
        """
        _logger.info('******************* process_mobile_order **************')
        try:
            # Validation des données d'entrée
            raw_data = request.httprequest.data
            data = json.loads(raw_data.decode('utf-8')) if raw_data else {}
            order_data = data.get('order', {})

            if not order_data or 'lines' not in order_data:
                return http.Response(json.dumps({"error": "Invalid order data"}),
                                     content_type='application/json', status=400)

            # Extraction des paramètres
            pos_config_id = data.get('pos_config_id')
            table_identifier = data.get('table_identifier')
            access_token = data.get('access_token')
            device_type = data.get('device_type', 'mobile')
            takeaway = order_data.get('takeaway', False)
            discount_code = order_data.get('discount_code')
            mobile_user_id = order_data.get('mobile_user_id')
            subscription_id = order_data.get('subscription_id')
            menupro_id = order_data.get('menupro_id')
            paid_online = order_data.get('paid_online', False)
            menupro_name = order_data.get('menupro_name')

            is_qr_mobile_order = (device_type == 'mobile' and
                                  order_data.get('origine') == 'mobile')

            _logger.info(f"mobile_user_id reçu: {mobile_user_id}")
            _logger.info(f"subscription_id reçu: {subscription_id}")
            _logger.info(f"menupro_id reçu: {menupro_id}")
            _logger.info(f"takeaway reçu: {takeaway}")
            _logger.info(f"paid_online reçu: {paid_online}")
            _logger.info(f"menupro_name reçu: {menupro_name}")

            # Validation des paramètres requis
            required_params = [pos_config_id, access_token]
            if not takeaway:
                required_params.append(table_identifier)

            if not all(required_params):
                missing = [p for p in ['pos_config_id', 'table_identifier', 'access_token']
                           if not locals().get(p.replace('_', '').replace('identifier', '_identifier'))]
                return http.Response(json.dumps({"error": f"Missing required parameters: {missing}"}),
                                     content_type='application/json', status=400)

            # Validation de la configuration POS
            pos_config = request.env['pos.config'].sudo().browse(pos_config_id)
            if not pos_config or not pos_config.current_session_id:
                return http.Response(json.dumps({"error": "POS configuration or session not found"}),
                                     content_type='application/json', status=400)

            # Validation de la table (seulement pour dine-in)
            restaurant_table = None
            if not takeaway:
                restaurant_table = request.env['restaurant.table'].sudo().search([
                    ('identifier', '=', table_identifier),
                ], limit=1)

                if not restaurant_table:
                    return http.Response(json.dumps({"error": f"Table '{table_identifier}' not found"}),
                                         content_type='application/json', status=404)
            else:
                # Pour takeaway, créer une table fictive ou utiliser une table par défaut
                restaurant_table = request.env['restaurant.table'].sudo().search([], limit=1)
                if not restaurant_table:
                    return http.Response(json.dumps({"error": "No default table found for takeaway orders"}),
                                         content_type='application/json', status=400)

            # Récupération de l'ID du restaurant
            restaurant_id = request.env['ir.config_parameter'].sudo().get_param('restaurant_id')
            _logger.info(f"Restaurant ID utilisé : {restaurant_id}")

            # Assurance de l'existence de la configuration de remise
            if restaurant_id:
                request.env['restaurant.discount.config'].sudo().ensure_config_exists()
     

            # *** RECHERCHE DE COMMANDE EXISTANTE - ADAPTÉE TAKEAWAY ***
            if takeaway:
                # Pour takeaway, chercher une floating order existante avec le même mobile_user_id
                existing_order = request.env['pos.order'].sudo().search([
                    ('session_id', '=', pos_config.current_session_id.id),
                    ('state', '=', 'draft'),
                    ('table_id', '=', False),  # Floating order
                    ('takeaway', '=', True),
                    ('mobile_user_id', '=', mobile_user_id),
                ], limit=1)

                _logger.info(
                    f"Recherche floating order takeaway - mobile_user_id: {mobile_user_id}, trouvée: {bool(existing_order)}")
            else:
                # Pour dine-in, chercher par table comme avant
                existing_order = request.env['pos.order'].sudo().search([
                    ('table_id', '=', restaurant_table.id),
                    ('session_id', '=', pos_config.current_session_id.id),
                    ('state', '=', 'draft')
                ], limit=1)

                _logger.info(f"Recherche commande table {restaurant_table.table_number}, trouvée: {bool(existing_order)}")

            _logger.info(f"Commande existante trouvée: {existing_order.name if existing_order else 'Aucune'}")

            # Calcul du total avant remise
            discount_config = None
            discount_product_name = None
            if discount_code:
                discount_config = self.get_restaurant_discount_config(restaurant_id, discount_code)
                discount_product_name = discount_config['discount_name']

            total_before_discount = self.calculate_total_before_discount(existing_order, discount_product_name)

            # Traitement des lignes de commande
            line_operations, new_lines_total = self.process_order_lines(order_data, pos_config, existing_order)
            total_before_discount += new_lines_total

            # Application de la remise QR mobile
            discount_info = None
            if is_qr_mobile_order and restaurant_id:
                # Si un code promo spécifique est fourni, l'utiliser
                if discount_code:
                    discount_info = self.apply_qr_mobile_discount(total_before_discount, restaurant_id, discount_code)
                    if discount_info:
                        _logger.info(
                            f"Remise QR mobile appliquée (code spécifique) : {discount_info['discount_amount']:.2f}€ sur {total_before_discount:.2f}€")
                        discount_line_op = self.process_discount_line(discount_info, existing_order, discount_code)
                        line_operations.append(discount_line_op)
                else:
                    # Sinon, appliquer automatiquement le code promo par défaut pour mobile
                    discount_info = self.apply_default_mobile_promo(total_before_discount, restaurant_id)
                    if discount_info:
                        _logger.info(
                            f"Remise mobile par défaut appliquée automatiquement : {discount_info['discount_amount']:.2f}€ sur {total_before_discount:.2f}€")
                        discount_line_op = self.process_discount_line(discount_info, existing_order, 'MOBILE_DEFAULT')
                        line_operations.append(discount_line_op)

            # Mise à jour ou création de commande
            if existing_order:
                _logger.info("=== MISE À JOUR COMMANDE EXISTANTE ===")
                updated_order = self.update_existing_order(
                    existing_order,
                    line_operations,
                    access_token,
                    takeaway,
                    menupro_id,
                    mobile_user_id,
                    subscription_id,
                    paid_online
                )
                response_data = self.build_response_data(
                    updated_order,
                    restaurant_id,
                    discount_info,
                    total_before_discount,
                    is_update=True,
                    mobile_user_id=mobile_user_id,
                    subscription_id=subscription_id
                )
            else:
                _logger.info("=== CRÉATION NOUVELLE COMMANDE ===")
                new_order_result = self.create_new_order(
                    pos_config,
                    restaurant_table,
                    line_operations,
                    access_token,
                    takeaway,
                    menupro_id,
                    mobile_user_id,
                    subscription_id,
                    paid_online,
                    menupro_name
                )
                response_data = self.build_response_data(
                    new_order_result,
                    restaurant_id,
                    discount_info,
                    total_before_discount,
                    is_update=False,
                    mobile_user_id=mobile_user_id,
                    subscription_id=subscription_id
                )

            # Debug de la réponse
            _logger.info(f"=== RESPONSE DATA DEBUG ===")
            if isinstance(response_data, dict):
                _logger.info(f"Response keys: {list(response_data.keys())}")
                _logger.info(f"takeaway in response: {response_data.get('takeaway', 'NOT_FOUND')}")
                _logger.info(f"mobile_user_id in response: {response_data.get('mobile_user_id', 'NOT_FOUND')}")
            _logger.info(f"=== END RESPONSE DEBUG ===")

            # Retour de la réponse
            json_response = json.dumps(response_data, default=json_default)
            return http.Response(json_response, content_type='application/json', status=200)

        except Exception as e:
            _logger.exception("Error processing mobile order: %s", str(e))
            return http.Response(json.dumps({"error": str(e)}), content_type='application/json', status=500)



    @http.route('/update_print_url', type='http', auth='public', methods=['POST'], csrf=False)
    def update_print_url(self, **kwargs):
            _logger.info('******************* update_print_url **************')
            try:
                # Récupération et parsing du body
                raw_data = request.httprequest.data
                data = json.loads(raw_data.decode('utf-8')) if raw_data else {}

                url = data.get('url', "")
                if not url:
                    return http.Response(
                        json.dumps({"error": "Invalid url"}),
                        content_type='application/json', status=400
                    )

                # 🔥 Mise à jour du paramètre système
                request.env['ir.config_parameter'].sudo().set_param('print_url', url)

                message = {"message": "successful update printing url", "url": url}
                return http.Response(
                    json.dumps(message),
                    content_type='application/json',
                    status=200
                )

            except Exception as e:
                _logger.exception("Error processing update printing url: %s", str(e))
                return http.Response(
                    json.dumps({"error": str(e)}),
                    content_type='application/json',
                    status=500
                )

    @http.route('/get_print_url', type='http', auth='public', methods=['GET'], csrf=False)
    def get_print_url(self, **kwargs):
        try:
            print_url = request.env['ir.config_parameter'].sudo().get_param('print_url')
            if print_url:
                return http.Response(
                    json.dumps({"print_url": print_url}),
                    content_type='application/json',
                    status=200
                )
            else:
                return http.Response(
                    json.dumps({"print_url": None}),
                    content_type='application/json',
                    status=200
                )
        except Exception as e:
            _logger.exception("Error retrieving print_url: %s", str(e))
            return http.Response(
                json.dumps({"error": str(e)}),
                content_type='application/json',
                status=500
            )

