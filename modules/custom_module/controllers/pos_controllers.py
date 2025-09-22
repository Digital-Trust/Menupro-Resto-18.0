from odoo import http, tools, fields
from odoo.http import request
import json
import requests
import logging

_logger = logging.getLogger(__name__)


class PosOrderController(http.Controller):

    @http.route('/pos/send_removed_dish_notification', type='json', auth='user', methods=['POST'], csrf=False)
    def send_removed_dish_notification(self, line_data, cashier_name, order_id, mobile_user_id, subscription_id,
                                       order_menupro_id, restaurant_id):
        """
        Contrôleur sécurisé pour envoyer les notifications de plats supprimés
        """
        try:
            # Récupération de la clé secrète depuis la configuration Odoo
            odoo_secret_key = tools.config.get("odoo_secret_key")

            if not odoo_secret_key:
                _logger.error("Clé secrète Odoo non configurée")
                return {"success": False, "error": "Configuration manquante"}

            # Validation des données obligatoires
            if not all([line_data, cashier_name, order_id, mobile_user_id]):
                return {"success": False, "error": "Données manquantes"}

            # Préparation du payload
            payload = {
                "line": line_data,
                "cashier": cashier_name,
                "order_id": order_id,
                "date": fields.Datetime.now().isoformat(),
                "mobile_user_id": mobile_user_id,
                "subscription_id": subscription_id,
                "order_menupro_id": order_menupro_id,
                "restaurant_id": restaurant_id,
            }

            # Headers sécurisés
            headers = {
                "x-api-key": odoo_secret_key,
                "Content-Type": "application/json",
            }

            # Envoi de la notification
            response = requests.post(
                "http://localhost:3000/Notifications/Removed-dish/notif",
                headers=headers,
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                _logger.info(f"Notification envoyée avec succès pour la commande {order_id}")
                return {"success": True, "data": response.json()}
            else:
                _logger.error(f"Erreur notification: {response.status_code} - {response.text}")
                return {"success": False, "error": f"Erreur serveur: {response.status_code}"}

        except requests.exceptions.Timeout:
            _logger.error("Timeout lors de l'envoi de la notification")
            return {"success": False, "error": "Timeout"}
        except requests.exceptions.ConnectionError:
            _logger.error("Erreur de connexion lors de l'envoi de la notification")
            return {"success": False, "error": "Connexion échouée"}
        except Exception as e:
            _logger.error(f"Erreur inattendue lors de l'envoi de notification: {str(e)}")
            return {"success": False, "error": "Erreur interne"}

    @http.route('/pos/update_cashier', type='json', auth='user', methods=['POST'], csrf=False)
    def update_order_cashier(self, order_id, cashier_id):
        """
        Contrôleur pour mettre à jour le cashier d'une commande
        """
        try:
            order = request.env['pos.order'].browse(order_id)
            cashier = request.env['hr.employee'].browse(cashier_id)

            if not order.exists() or not cashier.exists():
                return {"success": False, "error": "Commande ou cashier introuvable"}

            order.write({
                'cashier': cashier.name,
                'employee_id': cashier.id,
            })

            return {"success": True, "message": "Cashier mis à jour"}

        except Exception as e:
            _logger.error(f"Erreur mise à jour cashier: {str(e)}")
            return {"success": False, "error": "Erreur interne"}