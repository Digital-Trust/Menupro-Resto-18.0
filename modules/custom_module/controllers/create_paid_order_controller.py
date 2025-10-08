import json
import logging
from odoo import http, fields
from odoo.http import request
import uuid
from datetime import date, datetime
from ..utils.security_utils import mask_sensitive_data

_logger = logging.getLogger(__name__)


def json_default(obj):
    """Fonction de sérialisation personnalisée pour les objets non standards"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return obj.decode('utf-8')
    raise TypeError(f"Type {type(obj)} not serializable")


class CreatePaidOrderController(http.Controller):

    def get_restaurant_discount_config(self, restaurant_id=None, discount_code=None):
        """
        Récupère la configuration de remise pour un restaurant et code spécifiques
        """
        config_model = request.env['restaurant.discount.config'].sudo()
        return config_model.get_config_for_code(restaurant_id, discount_code)

    def apply_qr_mobile_discount(self, amount_total, restaurant_id=None, discount_code=None):
        """
        Applique une remise QR mobile selon le restaurant et le code de remise
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

    def get_or_create_discount_product(self, discount_name):
        """
        Récupère ou crée un produit de remise
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

    def process_order_lines(self, order_data, pos_config):
        """
        Traite les lignes de commande et calcule les totaux
        """
        line_operations = []
        total_before_discount = 0.0

        for line in order_data['lines']:
            product = request.env['product.product'].sudo().search([
                ('menupro_id', '=', line.get('menupro_id'))
            ], limit=1)

            if not product:
                _logger.warning(f"Produit non trouvé pour menupro_id: {line.get('menupro_id')}")
                continue

            # Récupération des données de la ligne
            qty = line.get('qty', 1)
            note = line.get('note', '')
            attribute_value_ids = line.get('attribute_value_ids', [])
            custom_attribute_value_ids = line.get('custom_attribute_value_ids', [])
            price_extra = line.get('price_extra', 0.0)
            price_unit = product.lst_price + price_extra

            _logger.info(f"Traitement ligne - Produit: {product.name}, Qty: {qty}, Prix unitaire: {price_unit}")

            # Calcul des taxes
            taxes_res = product.taxes_id.compute_all(
                price_unit,
                currency=pos_config.pricelist_id.currency_id,
                quantity=qty,
                product=product
            )
            total_before_discount += taxes_res['total_included']

            # Génération des données de ligne
            line_uuid = str(uuid.uuid4())
            attribute_value_ids_clean = [aid for aid in attribute_value_ids if
                                         request.env['product.template.attribute.value'].sudo().browse(aid).exists()]
            attribute_names = request.env['product.template.attribute.value'].sudo().browse(
                attribute_value_ids_clean).mapped('name')
            full_product_name = f"{product.name} ({', '.join(attribute_names)})" if attribute_names else product.name

            line_data = {
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

            line_operations.append((0, 0, line_data))
            _logger.info(f"Ligne ajoutée - Total TTC: {taxes_res['total_included']}")

        return line_operations, total_before_discount

    def process_discount_line(self, discount_info, discount_code):
        """
        Traite la ligne de remise
        """
        discount_product = self.get_or_create_discount_product(discount_info['discount_name'])

        # Création de la note de remise
        discount_note = f'Remise QR mobile {discount_info["discount_percentage"]:.1f}% (Code: {discount_code})'
        if discount_info.get('capped'):
            discount_note += f' (plafonnée à {discount_info["max_discount"]}€)'

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

    def create_new_order(self, pos_config, restaurant_table, line_operations, access_token, takeaway, menupro_id,
                         mobile_user_id=None, subscription_id=None, employee_id=None):
        """
        Crée une nouvelle commande
        """
        sequence = request.env['ir.sequence'].sudo().next_by_code('pos.order')
        amount_total = sum(line[2]['price_subtotal_incl'] for line in line_operations)
        amount_tax = sum(line[2]['price_subtotal_incl'] - line[2]['price_subtotal'] for line in line_operations)

        _logger.info(f"Création commande - Séquence: {sequence}, Total: {amount_total}")

        # Configuration de base de la commande
        order_vals = {
            'name': sequence,
            'pos_reference': sequence,
            'session_id': pos_config.current_session_id.id,
            'date_order': fields.Datetime.now(),
            'lines': line_operations,
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
        }

        # Add employee_id if provided
        if employee_id:
            order_vals['employee_id'] = employee_id

        # Gestion takeaway/floating order
        if takeaway:
            order_vals.update({
                'table_id': False,
                'takeaway': True,
                'floating_order_name': f"TKO-{sequence}",
            })
            _logger.info(f"Création floating order takeaway: {sequence}")
        else:
            order_vals.update({
                'table_id': restaurant_table.id,
                'takeaway': False,
            })
            _logger.info(
                f"Création commande table: {restaurant_table.table_number if hasattr(restaurant_table, 'table_number') else restaurant_table.id}")

        # Créer la commande
        order = request.env['pos.order'].sudo().create(order_vals)
        _logger.info(f"Commande créée: {order.name} (ID: {order.id})")

        return order

    def create_payment(self, order, payment_method_id, amount=None):
        """
        Crée un paiement pour la commande
        """
        if amount is None:
            amount = order.amount_total

        # Validation de la méthode de paiement par ID
        payment_method = request.env['pos.payment.method'].sudo().browse(payment_method_id)
        if not payment_method.exists():
            raise ValueError(f"Méthode de paiement avec ID '{payment_method_id}' non trouvée")

        # Calculer le nouveau montant payé localement avant d'écrire
        current_paid = float(order.amount_paid or 0.0)
        new_paid = current_paid + float(amount or 0.0)

        # Déterminer l'état cible
        target_state = 'paid' if new_paid >= float(order.amount_total or 0.0) else 'draft'

        # Créer le paiement
        payment_vals = {
            'pos_order_id': order.id,
            'amount': amount,
            'payment_method_id': payment_method.id,
            'payment_date': fields.Datetime.now(),
            'session_id': order.session_id.id
        }

        payment = request.env['pos.payment'].sudo().create(payment_vals)
        _logger.info(f"Paiement créé: {payment.id} - Montant: {amount} - Méthode: {payment_method.name}")

        # Mettre à jour le montant payé et l'état en une seule opération
        order.write({
            'amount_paid': new_paid,
            'state': target_state
        })

        # Re-browse pour être sûr d'avoir les dernières valeurs (optionnel mais pratique)
        order = request.env['pos.order'].sudo().browse(order.id)

        _logger.info(
            f"Commande {order.name} - État: {order.state} - Montant payé: {order.amount_paid}/{order.amount_total}")

        return payment

    def finalize_paid_order(self, order):
        """
        Finalise une commande payée pour s'assurer qu'elle est dans le bon état
        """
        try:
            # Vérifier que la commande est entièrement payée
            if order.amount_paid >= order.amount_total:
                # Forcer l'état à 'paid'
                order.write({
                    'state': 'paid',
                })

                # Essayer de valider la commande avec les méthodes Odoo standard
                if hasattr(order, '_onchange_amount_all'):
                    order._onchange_amount_all()

                # Forcer le commit pour s'assurer que les changements sont persistés
                request.env.cr.commit()

                _logger.info(f"Commande {order.name} finalisée avec succès - État: {order.state}")
            else:
                _logger.warning(
                    f"Commande {order.name} pas entièrement payée: {order.amount_paid}/{order.amount_total}")

        except Exception as e:
            _logger.error(f"Erreur lors de la finalisation de la commande {order.name}: {e}")
            # Ne pas lever l'exception pour ne pas casser le processus principal

    def build_response_data(self, order, payment, restaurant_id, discount_info=None, total_before_discount=0.0,
                            mobile_user_id=None, subscription_id=None):
        """
        Construit les données de réponse
        """
        # Informations sur la table
        table_info = None
        if order.table_id:
            table_info = {
                'id': order.table_id.id,
                'identifier': getattr(order.table_id, 'identifier', None),
                'table_number': getattr(order.table_id, 'table_number', None),
                'display_name': order.table_id.display_name,
            }

        response_data = {
            "success": True,
            "order_id": order.id,
            "order_name": order.name,
            "pos_reference": order.pos_reference,
            "amount_total": order.amount_total,
            "amount_paid": order.amount_paid,
            "amount_tax": order.amount_tax,
            "state": order.state,
            "takeaway": getattr(order, 'takeaway', False),
            "floating_order_name": getattr(order, 'floating_order_name', None),
            "table_info": table_info,
            "restaurant_id": restaurant_id,
            "mobile_user_id": mobile_user_id,
            "subscription_id": subscription_id,
            "payment_info": {
                "payment_id": payment.id,
                "amount": payment.amount,
                "method_name": payment.payment_method_id.name,
                "method_id": payment.payment_method_id.id,
                "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
                "payment_uuid": getattr(payment, 'uuid', None),
            },
            "message": f"Commande payée créée avec succès: {order.name}"
        }

        # Ajout des informations de remise si applicable
        if discount_info:
            response_data["discount_applied"] = {
                "discount_name": discount_info["discount_name"],
                "discount_percentage": discount_info["discount_percentage"],
                "original_percentage": discount_info["original_percentage"],
                "discount_amount": discount_info["discount_amount"],
                "original_total": total_before_discount,
                "final_total": order.amount_total,
                "capped": discount_info.get("capped", False),
                "max_discount": discount_info.get("max_discount"),
                "min_amount": discount_info.get("min_amount")
            }

        return response_data

    @http.route('/create_paid_order_in_session', type='http', auth='public', methods=['POST'], csrf=False)
    def create_paid_order_in_session(self, **kwargs):
        """
        Crée une commande payée directement
        """
        _logger.info('******************* create_paid_order_in_session **************')
        try:
            # Validation des données d'entrée
            raw_data = request.httprequest.data
            data = json.loads(raw_data.decode('utf-8')) if raw_data else {}

            masked_data = mask_sensitive_data(data)
            _logger.info(f"Données reçues: {json.dumps(masked_data, indent=2)}")

            order_data = data.get('order', {})
            if not order_data or 'lines' not in order_data:
                return http.Response(json.dumps({"error": "Invalid order data"}),
                                     content_type='application/json', status=400)

            # Extraction des paramètres
            session_id = data.get('session_id')
            employee_id = data.get('employee_id')
            table_id = data.get('table_id')
            payment_method_id = data.get('payment_method_id')  # Changed from payment_method
            takeaway = order_data.get('takeaway', False)
            discount_code = order_data.get('discount_code')
            mobile_user_id = order_data.get('mobile_user_id')
            subscription_id = order_data.get('subscription_id')
            menupro_id = order_data.get('menupro_id')
            device_type = data.get('device_type', 'mobile')

            _logger.info(f"Création commande payée - Session: {session_id}, Employee: {employee_id}, Table: {table_id}")
            _logger.info(f"Takeaway: {takeaway}, Payment method ID: {payment_method_id}")
            _logger.info(f"mobile_user_id: {mobile_user_id}, subscription_id: {subscription_id}")

            # Validation des paramètres requis
            required_params = [session_id, employee_id, payment_method_id]
            if not takeaway:
                required_params.append(table_id)

            if not all(required_params):
                missing = []
                if not session_id: missing.append('session_id')
                if not employee_id: missing.append('employee_id')
                if not payment_method_id: missing.append('payment_method_id')
                if not takeaway and not table_id: missing.append('table_id')
                return http.Response(json.dumps({"error": f"Missing required parameters: {missing}"}),
                                     content_type='application/json', status=400)

            # Validation de la session POS
            pos_session = request.env['pos.session'].sudo().browse(session_id)
            if not pos_session or pos_session.state != 'opened':
                return http.Response(json.dumps({"error": "POS session not found or not opened"}),
                                     content_type='application/json', status=400)

            pos_config = pos_session.config_id

            # Validation de la table (seulement pour dine-in)
            restaurant_table = None
            if not takeaway:
                restaurant_table = request.env['restaurant.table'].sudo().browse(table_id)
                if not restaurant_table:
                    return http.Response(json.dumps({"error": f"Table with ID {table_id} not found"}),
                                         content_type='application/json', status=404)
            else:
                # Pour takeaway, utiliser une table par défaut ou None
                restaurant_table = request.env['restaurant.table'].sudo().search([], limit=1)

            # Récupération de l'ID du restaurant
            restaurant_id = request.env['ir.config_parameter'].sudo().get_param('restaurant_id')
            _logger.info(f"Restaurant ID utilisé : {restaurant_id}")

            # Assurance de l'existence de la configuration de remise
            if restaurant_id:
                request.env['restaurant.discount.config'].sudo().ensure_config_exists()

            # Traitement des lignes de commande
            line_operations, total_before_discount = self.process_order_lines(order_data, pos_config)
            _logger.info(f"Lignes traitées: {len(line_operations)}, Total avant remise: {total_before_discount}")

            # Application de la remise QR mobile si applicable
            discount_info = None
            is_qr_mobile_order = (device_type == 'mobile' and order_data.get('origine') == 'mobile')

            if is_qr_mobile_order and restaurant_id and discount_code:
                discount_info = self.apply_qr_mobile_discount(total_before_discount, restaurant_id, discount_code)
                if discount_info:
                    _logger.info(
                        f"Remise QR mobile appliquée : {discount_info['discount_amount']:.2f}€ sur {total_before_discount:.2f}€")
                    discount_line_op = self.process_discount_line(discount_info, discount_code)
                    line_operations.append(discount_line_op)

            # Création de la commande
            access_token = str(uuid.uuid4())
            order = self.create_new_order(
                pos_config,
                restaurant_table,
                line_operations,
                access_token,
                takeaway,
                menupro_id,
                mobile_user_id,
                subscription_id,
                employee_id
            )

            # Création du paiement
            payment = self.create_payment(order, payment_method_id)
            try:
                self.finalize_paid_order(order)
            except Exception:
                _logger.exception("Erreur lors de la finalisation de la commande après paiement")

            # Construction de la réponse
            response_data = self.build_response_data(
                order,
                payment,
                restaurant_id,
                discount_info,
                total_before_discount,
                mobile_user_id,
                subscription_id
            )

            _logger.info(f"Commande payée créée avec succès: {order.name} - État: {order.state}")

            # Retour de la réponse
            json_response = json.dumps(response_data, default=json_default)
            return http.Response(json_response, content_type='application/json', status=200)

        except ValueError as ve:
            _logger.error(f"Erreur de validation: {str(ve)}")
            return http.Response(json.dumps({"error": str(ve)}), content_type='application/json', status=400)
        except Exception as e:
            _logger.exception("Error creating paid order: %s", str(e))
            return http.Response(json.dumps({"error": str(e)}), content_type='application/json', status=500)