from odoo import models, fields, api, tools
import requests
import logging
import json
from datetime import datetime

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    menupro_id = fields.Char(string='MenuPro ID')
    origine = fields.Char(string='Origine')
    ticket_number = fields.Integer(string='Ticket Number', help='Ticket number for the order')
    mobile_user_id = fields.Char(
        string="Mobile User ID",
        help="Identifiant de l'utilisateur mobile ayant passé la commande"
    )
    subscription_id = fields.Char(
        string="Mobile User Subscription ID",
        help="Identifiant de l'abonnement utilisateur mobile pour la notification"
    )
    paid_online = fields.Boolean(
        string="Paid Online",
        default=False,
        help="Indique si la commande a été payée en ligne"
    )



    def _get_config(self):
        """Charge et valide la config une seule fois par thread."""
        if hasattr(self.env, "_mp_config"):
            return self.env._mp_config

        ICParam = self.env['ir.config_parameter'].sudo()

        cfg = {
            'notif_url': tools.config.get('notif_url'),
            'secret_key': tools.config.get('secret_key'),
            'odoo_secret_key': tools.config.get('odoo_secret_key'),
            'restaurant_id': ICParam.get_param('restaurant_id'),
        }

        for k, v in cfg.items():
            if not v:
                _logger.error("%s is missing in config", k)
                raise UserError(f"L’option '{k}' est manquante dans la configuration.")

        self.env._mp_config = cfg
        _logger.info("\033[92mMenuPro config OK\033[0m")
        return cfg


    def _call_mp(self, method, url, json=None):
        cfg = self._get_config()

        try:
            resp = requests.request(method, url, json=json, timeout=10)
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except Exception as e:
            _logger.warning("MenuPro %s %s failed → %s", method, url, e)
            raise


    def _build_payload(self):
        cfg = self._get_config()
        self.ensure_one()
        return {
            "menupro_id": self.menupro_id,
            "write_date": self.write_date.isoformat() if self.write_date else None,
            "cashier": self.cashier,
            "pos_reference": self.pos_reference,
            "state": self.state,
            "restaurant_id": cfg['restaurant_id'],
            "subscription_id":self.subscription_id,
            "mobile_user_id": self.mobile_user_id,

        }

    def action_pos_order_cancel(self):
        result = super().action_pos_order_cancel()

        for order in self:

            if order.mobile_user_id:
                try:
                    cfg = order._get_config()
                    base = cfg.get('notif_url')
                    if base:
                        payload = order._build_payload()
                        _logger.info("payload cancel notif: %s", payload)

                        data = order._call_mp(
                            "POST",
                            f"{base}/Send-cancel-order-notif",
                            payload
                        )
                        _logger.info("cancel notif response: %s", data)
                except Exception as e:
                    _logger.warning("Impossible d'envoyer la notif annulation: %s", e)
        return result

    @api.model
    def sync_from_ui(self, orders):
        # old_states = {}
        # for order in orders:
        #     if order.get("id"):
        #         pos_order = self.browse(order["id"])
        #         if not pos_order.exists():
        #             continue
        #         old_states[order["id"]] = {
        #             "is_edited": pos_order.is_edited,
        #             "has_deleted_line": pos_order.has_deleted_line,
        #             "lines": pos_order.lines,
        #             "last_order_preparation_change": pos_order.last_order_preparation_change,
        #         }

        result = super().sync_from_ui(orders)
        created_orders = result.get('pos.order', {})
        for order in created_orders:
            # pos_order = self.browse(order["id"])
            # if pos_order.mobile_user_id:
            #     old_state = old_states.get(order["id"], {})
            #     if (
            #             old_state.get("is_edited") != pos_order.is_edited
            #             or old_state.get("has_deleted_line") != pos_order.has_deleted_line
            #         or old_state.get("lines") != pos_order.lines
            #         or old_state.get('pos_order.last_order_preparation_change') != pos_order.pos_order.last_order_preparation_change
            #     ):
            #         print(f"⚡ Order {pos_order.id} has changed!")
            #         print("Before:", old_state)
            #         print("After:", {
            #             "is_edited": pos_order.is_edited,
            #             "has_deleted_line": pos_order.has_deleted_line,
            #             "lines": pos_order.lines,
            #             "last_order_preparation_change": pos_order.last_order_preparation_change,
            #         })
            #         try:
            #             cfg = pos_order._get_config()
            #             base = cfg.get('notif_url')
            #             if base:
            #                 payload = pos_order._build_payload()
            #                 _logger.info("payload cancel notif: %s", pos_order)
            #
            #                 data = pos_order._call_mp(
            #                     "POST",
            #                     f"{base}/Send-cancel-order-notif",
            #                     payload
            #                 )
            #                 _logger.info("cancel notif response: %s", data)
            #         except Exception as e:
            #             _logger.warning("Impossible d'envoyer la notif annulation: %s", e)
            self._sync_reservation(order)
            self._sync_to_menupro(order)
            # Generate a ticket_number
            if 'ticket_number' not in order:
                order['ticket_number'] = self.get_today_ticket_number()

        return result

    @api.model
    def _sync_reservation(self, order):
        odoo_secret_key = tools.config.get("odoo_secret_key")
        table_id = order.get('table_id')
        # print("order table", table_id)

        restaurant_table = self.env['restaurant.table'].search([('id', '=', table_id)])
        # print("restaurant_table", restaurant_table)

        if restaurant_table:
            menupro_id = restaurant_table.menupro_id

            if menupro_id:
                try:
                    # Vérifie si la commande est annulée
                    if order.get('state') in ["cancel", "paid"]:
                        data = {'reserved': False}
                    else:
                        data = {'reserved': True}

                    response = requests.patch(
                        f'https://api.menupro.tn/restaurant-tables/{menupro_id}',
                        json=data,
                        headers={'x-odoo-key': odoo_secret_key}
                    )
                    response.raise_for_status()
                except requests.RequestException as e:
                    _logger.error("API request failed for table %s: %s", menupro_id, e, exc_info=True)
            else:
                _logger.warning("Invalid menupro_id for table: %s", menupro_id)




    @api.model
    def _sync_to_menupro(self, order):
        restaurant_id = self.env['ir.config_parameter'].sudo().get_param('restaurant_id')
        odoo_secret_key = tools.config.get("odoo_secret_key")
        api_url = "https://api.finance.visto.group/orders/order/upsert"


        if not restaurant_id or not odoo_secret_key:
            _logger.error("Secret key or restaurant ID not configured. Skipped sync to menupro")
            return

        headers = {'x-odoo-key': odoo_secret_key}
        payload = self._prepare_api_payload(order, restaurant_id)
        # print("Payload to be sent to our server =>", payload)

        try:
            response = requests.patch(api_url, json=payload, headers=headers)
            # print('response of finance =>', response.text)
        except Exception as e:
            _logger.error("Error API: %s", str(e))
            raise

        if response.status_code == 200:
            response_data = response.json().get("data")
            menupro_id = response_data.get('menuproId')
            if menupro_id:
                self._update_menupro_id(menupro_id, order.get('id'))
        else:
            _logger.error(f"Failed to sync to Menupro order with ID")

    @api.model
    def _update_menupro_id(self, menupro_id, order_id):
        pos_order = self.env['pos.order'].sudo().search([('id', '=', order_id)], limit=1)
        if pos_order:
            pos_order.write({'menupro_id': menupro_id})
            # print(f"Order {pos_order.name} updated with menupro_id {menupro_id}")
        else:
            _logger.warning(f"No POS order found with ID {order_id}")

    @api.model
    def _prepare_api_payload(self, order_data, restaurant_id):
        try:
            # Formulate date_order to ISO format
            date_order = order_data.get('date_order')
            if isinstance(date_order, datetime):
                date_order = date_order.isoformat()

            payload = {
                "restaurantId": restaurant_id,
                "order": {
                    "id": order_data.get('id'),
                    "name": order_data.get('pos_reference', ''),
                    "amount_paid": order_data.get('amount_paid', 0),
                    "amount_total": order_data.get('amount_total', 0),
                    "amount_tax": order_data.get('amount_tax', 0),
                    "amount_return": order_data.get('amount_return', 0),
                    "lines": [],
                    "statement_ids": [],
                    "pos_session_id": order_data.get('session_id'),
                    "pricelist_id": order_data.get('pricelist_id', False),
                    "partner_id": order_data.get('partner_id', False),
                    "user_id": order_data.get('user_id'),
                    "uid": order_data.get('uuid', ''),
                    "sequence_number": order_data.get('sequence_number', 0),
                    "date_order": date_order,
                    "fiscal_position_id": order_data.get('fiscal_position_id', False),
                    "server_id": False,
                    "to_invoice": order_data.get('to_invoice', False),
                    "is_tipped": order_data.get('is_tipped', False),
                    "tip_amount": order_data.get('tip_amount', 0),
                    "access_token": order_data.get('access_token', ''),
                    "last_order_preparation_change": order_data.get('last_order_preparation_change', ''),
                    "ticket_code": order_data.get('ticket_code', ''),
                    "table_id": order_data.get('table_id'),
                    "customer_count": order_data.get('customer_count', 1),
                    "booked": True,
                    "employee_id": order_data.get('employee_id'),
                    "takeaway": order_data.get('takeaway'),
                    "menupro_id": order_data.get('menupro_id', False),
                    "status": "validate",
                    "menupro_fee": 0.5,
                    "subscription_id": order_data.get('subscription_id'),
                    "mobile_user_id": order_data.get('mobile_user_id'),
                    "paid_online": order_data.get('paid_online', False),
                    "ticketNumber": int(order_data.get('pos_reference', '0-0-0').split('-')[-1]),
                    "state": order_data.get('state', 'draft')
                }
            }

            # Get kitchen-ordered lines
            kitchen_lines = {}
            if order_data.get('last_order_preparation_change'):
                try:
                    prep_data = json.loads(order_data['last_order_preparation_change'])
                    kitchen_lines = prep_data.get('lines', {})
                except json.JSONDecodeError:
                    pass

            # Process all order lines
            for line_id in order_data['lines']:
                line = self.env['pos.order.line'].sudo().search([('id', '=', line_id)], limit=1)
                if not line:
                    continue

                line_data = {
                    "id": line.id,
                    "name": line.name,
                    "full_product_name": line.full_product_name or line.product_id.display_name,
                    "uuid": line.uuid,
                    "note": line.note or "",
                    "customer_note": line.customer_note or "",
                    "notice": line.notice or "",
                    "product_id": line.product_id.id,  # Use ID instead of model instance
                    "order_id": line.order_id.id,  # Use ID instead of model instance
                    "combo_parent_id": line.combo_parent_id.id if line.combo_parent_id else False,
                    "combo_item_id": line.combo_item_id.id if line.combo_item_id else False,
                    "price_type": line.price_type,
                    "price_unit": line.price_unit,
                    "qty": line.qty,
                    "price_subtotal": line.price_subtotal,
                    "price_subtotal_incl": line.price_subtotal_incl,
                    "discount": line.discount,
                    "skip_change": False,
                    "is_total_cost_computed": line.is_total_cost_computed,
                    "is_edited": line.is_edited,
                    "price_extra": line.price_extra,
                    "attribute_value_ids":line.attribute_value_ids.ids,
                    "is_sent_to_kitchen": line.uuid in kitchen_lines,
                }
                payload['order']['lines'].append(line_data)

            return payload
        except Exception as e:
            _logger.error("Error preparing API payload: %s", str(e))
            raise


    def get_today_ticket_number(self):
        """Get the count of orders made today (ignoring time)"""
        today = fields.Date.today()
        # Search for orders where the date part of date_order matches today
        orders_today = self.search_count([
            ('date_order', '>=', fields.Datetime.to_string(datetime.combine(today, datetime.min.time()))),
            ('date_order', '<=', fields.Datetime.to_string(datetime.combine(today, datetime.max.time()))),
        ])
        return orders_today + 1

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['ticket_number'] = self.get_today_ticket_number()
        return super().create(vals_list)



