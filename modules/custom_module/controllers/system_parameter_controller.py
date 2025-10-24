from odoo import http, fields
from odoo.http import request
import requests
import json
import logging
import time
_logger = logging.getLogger(__name__)


class SystemParameterController(http.Controller):

    @http.route('/custom_module/ticketNumber', type='json', auth='public', methods=['POST'])
    def get_ticket_number_by_order_id(self):
        data = json.loads(request.httprequest.data)
        pos_order_model = request.env['pos.order'].sudo()

        if not data.get('order_id'):
            count = pos_order_model.get_today_ticket_number()
            return {
                'ticket_number': count,
                'date': fields.Date.today().strftime('%Y-%m-%d')
            }

        try:
            order_id = int(data['order_id'])
        except (ValueError, TypeError):
            return {'error': f"Invalid order_id: {data['order_id']}. Must be an integer."}

        order = pos_order_model.search([('id', '=', order_id)], limit=1)
        if not order:
            return {'error': f"Order with ID {order_id} not found."}

        return {'ticket_number': order.ticket_number}

    @http.route('/custom_module/restaurant_id', type='json', auth='public', methods=['POST'])
    def get_restaurant_id(self):
        restaurant_id = request.env['ir.config_parameter'].sudo().get_param('restaurant_id')
        return {'restaurant_id': restaurant_id}

    @http.route('/custom_module/local_ip', type='json', auth='public', methods=['POST'])
    def get_local_ip(self):
        local_ip = request.env['ir.config_parameter'].sudo().get_param('local_ip')
        if not local_ip:
            return {'error': 'Local IP not configured'}

        print_receipt_url = f"{local_ip}/print_receipt"
        _logger.debug("Print receipt URL: %s", print_receipt_url)

        data = json.loads(request.httprequest.data.decode('utf-8'))
        _logger.debug("Print data received: %s", data)

        headers = {'Content-Type': 'application/json'}

        response = requests.post(print_receipt_url, headers=headers, json=data)
        _logger.debug("Print response status: %s", response.status_code)

        if response.status_code == 200:
            _logger.info("Print receipt successful, response: %s", response.status_code)
            return True
        else:
            return {'error': f"Failed to print: {response.status_code} - {response.text}"}

    @http.route('/custom_module/public_ip', type='json', auth='public', methods=['POST'])
    def get_public_ip(self):
        data = json.loads(request.httprequest.data.decode('utf-8'))
        config_params = request.env['ir.config_parameter'].sudo()
        print_url = config_params.get_param('print_url')

        if print_url:
            print_receipt_url = f"{print_url}/print_receipt"
        else:
            print_port = config_params.get_param('print_port')
            if not print_port:
                return {'error': 'Public IP "print_port" not configured'}
            print_receipt_url = f"http://{data['public_ip']}:{print_port}/print_receipt"

        headers = {'Content-Type': 'application/json'}

        try:
            response = requests.post(print_receipt_url, headers=headers, json=data, timeout=10)
            print("resp", response)
            _logger.debug("Print full order response status: %s", response.status_code)

            if response.status_code == 200:
                _logger.info("Print full order successful, response: %s", response.status_code)
                return True
            elif response.status_code == 503 and print_url:
                # Local tunnel unavailable, wait for new URL
                _logger.warning("Local tunnel unavailable (503), waiting for service restart...")
                old_url = print_url
                max_wait = 60  # Maximum 60 seconds
                wait_interval = 5  # Check every 5 seconds
                elapsed = 0

                while elapsed < max_wait:
                    time.sleep(wait_interval)
                    elapsed += wait_interval

                    refreshed_print_url = config_params.get_param('print_url')

                    if refreshed_print_url and refreshed_print_url != old_url:
                        _logger.info(f"New URL detected after {elapsed}s: {refreshed_print_url}")
                        print_receipt_url = f"{refreshed_print_url}/print_receipt"

                        # Retry the print request
                        response = requests.post(print_receipt_url, headers=headers, json=data, timeout=10)
                        print("response 2", response)
                        _logger.debug("Retry print response status: %s", response.status_code)

                        if response.status_code == 200:
                            _logger.info("Print successful on retry")
                            return True
                        else:
                            return {'error': f"Failed to print after retry: {response.status_code} - {response.text}"}

                    _logger.debug(f"Still waiting for new URL... ({elapsed}s elapsed)")

                return {'error': 'Print service restart timeout - no new URL received'}
            else:
                return {'error': f"Failed to print: {response.status_code} - {response.text}"}

        except requests.exceptions.Timeout:
            _logger.error("Print request timed out")
            return {'error': 'Print request timed out'}
        except requests.exceptions.RequestException as e:
            _logger.error("Print request failed: %s", str(e))
            return {'error': f'Print request failed: {str(e)}'}

