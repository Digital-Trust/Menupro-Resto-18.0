import requests
from datetime import datetime
from odoo import models, api, fields, tools
import logging
from odoo.exceptions import UserError
import pytz

_logger = logging.getLogger(__name__)

class PosConfig(models.Model):
    _inherit = 'pos.config'

    menuproId = fields.Char(string="MenuPro ID", copy=False)

    # ---------------- CONFIG ---------------- #
    def _get_config(self):
        """Charge et valide la config une seule fois par thread."""
        if hasattr(self.env, "_mp_config"):
            return self.env._mp_config

        ICParam = self.env['ir.config_parameter'].sudo()
        cfg = {
            'pos_config_url': tools.config.get('pos_config_url'),
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

    def _build_payload(self):
        cfg = self._get_config()
        self.ensure_one()
        return {
            "odooId": self.id,
            "name": self.name,
            "access_token": self.access_token,
            "active": self.active,
            "company_id": self.company_id.id if self.company_id else None,
            "uuid": self.uuid,
            "restaurant_id": cfg['restaurant_id'],

            # POS flags
            "takeaway": self.takeaway,
            "is_order_printer": self.is_order_printer,
            "iface_cashdrawer": self.iface_cashdrawer,
            "iface_printbill": self.iface_printbill,
            "iface_splitbill": self.iface_splitbill,
            "iface_big_scrollbars": self.iface_big_scrollbars,
            "iface_electronic_scale": self.iface_electronic_scale,
            "iface_print_auto": self.iface_print_auto,
            "iface_print_skip_screen": self.iface_print_skip_screen,
            "iface_print_via_proxy": self.iface_print_via_proxy,
            "iface_scan_via_proxy": self.iface_scan_via_proxy,
            "iface_tax_included": self.iface_tax_included,
            "iface_tipproduct": self.iface_tipproduct,
            "iface_available_categ_ids": self.iface_available_categ_ids.ids,
            "available_categ_menupro_ids": self.iface_available_categ_ids.mapped("menupro_id"),
            # Relations
            "printer_ids": self.printer_ids.ids,
            "restaurant_floor": self.floor_ids.ids,
            "restaurant_floor_menupro_ids":  self.floor_ids.mapped("menupro_id"),
            "basic_employee_ids": self.basic_employee_ids.ids,
            "advanced_employee_ids": self.advanced_employee_ids.ids,
            "payment_method_ids": self.payment_method_ids.ids,

            # Modules
            "module_pos_restaurant": self.module_pos_restaurant,
            "module_pos_hr": self.module_pos_hr,
            "module_pos_discount": self.module_pos_discount,
            "module_pos_avatax": self.module_pos_avatax,
            "module_pos_sms": self.module_pos_sms,
            "module_pos_restaurant_appointment": self.module_pos_restaurant_appointment,

            # Accounting / Journals
            "picking_type_id": self.picking_type_id.id if self.picking_type_id else None,
            "journal_id": self.journal_id.id if self.journal_id else None,
            "invoice_journal_id": self.invoice_journal_id.id if self.invoice_journal_id else None,
            "currency_id": self.currency_id.id if self.currency_id else None,
            "pricelist_id": self.pricelist_id.id if self.pricelist_id else None,
            "tip_product_id": self.tip_product_id.id if self.tip_product_id else None,
            "receipt_header": self.receipt_header or "",
            "receipt_footer": self.receipt_footer or "",

            # Discount / Rounding
            "manual_discount": self.manual_discount,
            "discount_pc": self.discount_pc,
            "discount_product_id": self.discount_product_id.id if self.discount_product_id else None,
            "cash_rounding": self.cash_rounding,
            "rounding_method": self.rounding_method or "",
            "amount_authorized_diff": self.amount_authorized_diff or 0,
            "only_round_cash_method": self.only_round_cash_method,

            # Stock / Picking
            "warehouse_id": self.warehouse_id.id if self.warehouse_id else None,
            "picking_policy": self.picking_policy or "direct",
            "ship_later": self.ship_later,
            "route_id": self.route_id.id if self.route_id else None,

            # Other options
            "proxy_ip": self.proxy_ip or "",
            "is_posbox": self.is_posbox,
            "auto_validate_terminal_payment": self.auto_validate_terminal_payment,
            "order_edit_tracking": self.order_edit_tracking,
            "orderlines_sequence_in_cart_by_category": self.orderlines_sequence_in_cart_by_category,
            "basic_receipt": self.basic_receipt,
            "is_closing_entry_by_product": self.is_closing_entry_by_product,
            "note_ids": self.note_ids.ids,
            "trusted_config_ids": self.trusted_config_ids.ids,

            # Self Ordering
            "self_ordering_takeaway": self.self_ordering_takeaway,
            "self_ordering_mode": self.self_ordering_mode,
            "self_ordering_default_language_id": self.self_ordering_default_language_id.id if self.self_ordering_default_language_id else None,
            "self_ordering_available_language_ids": self.self_ordering_available_language_ids.ids,
            "self_ordering_pay_after": self.self_ordering_pay_after,
            "self_ordering_default_user_id": self.self_ordering_default_user_id.id if self.self_ordering_default_user_id else None,
            "self_order_online_payment_method_id": self.self_order_online_payment_method_id.id if self.self_order_online_payment_method_id else None,
        }

    # ---------------- API CALL ---------------- #
    def _call_mp(self, method, url, json=None):
        cfg = self._get_config()
        headers = {
            "x-secret-key": cfg['secret_key'],
            "x-odoo-secret-key": cfg['odoo_secret_key'],
        }
        try:
            resp = requests.request(method, url, json=json, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except Exception as e:
            _logger.warning("MenuPro %s %s failed → %s", method, url, e)
            raise

    # ---------------- LOAD EXTRA MODELS ---------------- #
    def _pos_ui_models_to_load(self):
        result = super()._pos_ui_models_to_load()
        result.append('hr.employee')
        return result

    def _loader_params_hr_employee(self):
        return {
            'search_params': {
                'domain': [],
                'fields': ['id', 'name', 'allowed_floor_ids', 'can_manage_takeaway_orders'],
            }
        }

    def _get_pos_ui_hr_employee(self, params):
        return self.env['hr.employee'].search_read(
            params['search_params']['domain'],
            params['search_params']['fields']
        )

    # ---------------- CRUD OVERRIDES ---------------- #
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        cfg = self._get_config()
        base = cfg['pos_config_url']

        for rec in records:
            try:
                data = rec._call_mp("POST", base, rec._build_payload())
                rec.menuproId = data.get("_id")
            except Exception as e:
                _logger.error("Échec sync POS Config %s → %s", rec.id, e)

        return records

    def write(self, vals):
        res = super().write(vals)
        cfg = self._get_config()
        base = cfg['pos_config_url']
        print("vals=>",vals)
        print("self=========+++>",self)

        for rec in self:
            if rec.menuproId:  # déjà créé côté MenuPro → update
                try:
                    url = f"{base}/{rec.menuproId}"
                    rec._call_mp("PATCH", url, rec._build_payload())
                    print("rec._build_payload()",rec._build_payload())
                except Exception as e:
                    _logger.error("Échec sync update POS Config %s → %s", rec.id, e)
            else:
                data = rec._call_mp("POST", base, rec._build_payload())
                rec.menuproId = data.get("_id")
        return res

    def unlink(self):
        cfg = self._get_config()
        base = cfg['pos_config_url']


        for rec in self:
            if rec.menuproId:
                try:
                    url = f"{base}/{rec.menuproId}"
                    rec._call_mp("DELETE", url)
                except Exception as e:
                    _logger.error("Échec sync suppression POS Config %s → %s", rec.id, e)

        return super().unlink()



