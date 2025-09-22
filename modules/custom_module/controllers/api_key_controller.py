from odoo import http
from odoo.http import request


class ApiKeyController(http.Controller):

    @http.route('/generate_api_key', type='json', auth='user', methods=['POST'], csrf=False)
    def generate_key(self, **kwargs):
        user = request.env.user
        user.sudo().generate_api_key()
        return {"success": True, "api_key": user.api_key}
