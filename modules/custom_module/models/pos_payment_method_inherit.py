from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    menupro_online_payment = fields.Boolean(
        string="Menupro Online Payment",
        default=False,
        help="Indique si cette méthode de paiement est spécifiquement pour Menupro Online"
    )

    @api.model
    def ensure_online_menupro_payment_method(self, pos_config_id):
        """
        Ensures the 'Online Menupro' payment method exists for a given POS config.
        If it doesn't exist, it creates it.
        """
        _logger.info(f"Ensuring 'Online Menupro' payment method for POS config {pos_config_id}")

        # Search for an existing 'Online Menupro' payment method linked to this POS config
        existing_method = self.search([
            ('name', '=', 'Online Menupro'),
            ('pos_config_ids', 'in', [pos_config_id])
        ], limit=1)

        if existing_method:
            _logger.info(f"Payment method 'Online Menupro' already exists (ID: {existing_method.id}) for config {pos_config_id}.")
            return existing_method.id

        # If not found, create it
        _logger.info(f"Payment method 'Online Menupro' not found for config {pos_config_id}. Creating a new one.")

        # Get default journal and receivable account
        default_ids = self.get_default_online_payment_account_ids()
        journal_id = default_ids['journal_id']
        receivable_account_id = default_ids['receivable_account_id']

        if not journal_id or not receivable_account_id:
            _logger.error("Cannot create 'Online Menupro' payment method: Default journal or receivable account not found.")
            return False

        try:
            new_method = self.create({
                'name': 'Online Menupro',
                'type': 'bank',
                'use_payment_terminal': False,
                'is_online_payment': True,
                'payment_method_type': 'online',
                'sequence': 10,
                'active': True,
                'journal_id': journal_id,
                'receivable_account_id': receivable_account_id,
                'menupro_online_payment': True,
                'pos_config_ids': [(4, pos_config_id)],
            })
            _logger.info(f"Payment method 'Online Menupro' created successfully with ID: {new_method.id}")
            return new_method.id
        except Exception as e:
            _logger.error(f"Failed to create 'Online Menupro' payment method: {e}")
            return False

    @api.model
    def get_default_online_payment_account_ids(self):
        """
        RPC method to get default journal and receivable account IDs for online payment.
        """
        bank_journal = self.env['account.journal'].search([('type', '=', 'bank'), ('active', '=', True)], limit=1)
        receivable_account = self.env['account.account'].search([('code', '=like', '411%'), ('active', '=', True)], limit=1) # Assuming 411 is a common receivable account prefix

        return {
            'journal_id': bank_journal.id if bank_journal else False,
            'receivable_account_id': receivable_account.id if receivable_account else False,
        }

    @api.model
    def create_online_menupro_payment_method_rpc(self, pos_config_id, journal_id, receivable_account_id):
        """
        RPC method to create the 'Online Menupro' payment method on the backend.
        This method is called from the frontend.
        """
        _logger.info(f"RPC: Attempting to create 'Online Menupro' payment method for config {pos_config_id}")

        # Check if it already exists to prevent duplicates
        existing_method = self.search([
            ('name', '=', 'Online Menupro'),
            ('pos_config_ids', 'in', [pos_config_id])
        ], limit=1)

        if existing_method:
            _logger.info(f"RPC: Payment method 'Online Menupro' already exists (ID: {existing_method.id}) for config {pos_config_id}.")
            return existing_method.id

        # Get the POS config to link the payment method
        pos_config = self.env['pos.config'].browse(pos_config_id)
        if not pos_config:
            _logger.error(f"RPC: POS Config with ID {pos_config_id} not found.")
            return False

        # Create the payment method
        try:
            new_method = self.create({
                'name': 'Online Menupro',
                'type': 'bank',
                'use_payment_terminal': False,
                'is_online_payment': True,
                'payment_method_type': 'online',
                'sequence': 10,
                'active': True,
                'journal_id': journal_id,
                'receivable_account_id': receivable_account_id,
                'menupro_online_payment': True,
                'pos_config_ids': [(4, pos_config_id)], # Link to the POS config
            })
            _logger.info(f"RPC: Payment method 'Online Menupro' created successfully with ID: {new_method.id}")
            return new_method.id
        except Exception as e:
            _logger.error(f"RPC: Failed to create 'Online Menupro' payment method: {e}")
            return False
