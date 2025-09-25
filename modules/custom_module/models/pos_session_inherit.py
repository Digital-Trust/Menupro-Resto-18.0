from odoo import fields, models, api
import logging

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'
    ticket_number = fields.Integer(string='Ticket Number', help='A  number that is incremented with each order', default=1)

    def _load_pos_data_fields(self,config_id):
        result = super()._load_pos_data_fields(config_id)
        pos_order = self.env['pos.order']
        ticket_number = pos_order.get_today_ticket_number()
        # print("ticket_number", ticket_number)
        result.append('ticket_number')
        return result

    #Not used
    # def _close_session_action(self, amount_to_balance):
    #     installed_modules = self.env['ir.module.module'].sudo().search([
    #         ('name', 'in', ['mrp', 'stock']),
    #         ('state', '=', 'installed')
    #     ])
    #
    #     installed_modules_names = installed_modules.mapped('name')
    #     print('installed_modules_names',installed_modules_names)
    #
    #
    #     if 'mrp' in installed_modules_names and 'stock' in installed_modules_names:
    #         self._decrement_bom_components()
    #     self.write({'state': 'closed'})
    #     return super(PosSession, self)._close_session_action(amount_to_balance)

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        installed_modules = self.env['ir.module.module'].sudo().search([
            ('name', 'in', ['mrp', 'stock']),
            ('state', '=', 'installed')
        ])

        installed_modules_names = installed_modules.mapped('name')
        print('installed_modules_names',installed_modules_names)


        if 'mrp' in installed_modules_names and 'stock' in installed_modules_names:
            self._decrement_bom_components()
        self.write({'state': 'closed'})
        return super(PosSession, self).close_session_from_ui(bank_payment_method_diff_pairs)


    def _decrement_component_stock(self, component, qty_to_deduct, warnings):
        """
        Decrement the stock of a component in its preferred location
            or in the first available internal location.
        """
        preferred_location = component.product_tmpl_id.pos_preferred_location_id

        if preferred_location:
            stock_quant = self._get_or_create_stock_quant(component, preferred_location)
            f"Stock Quant pour {component.name} dans l'emplacement "
            f"{preferred_location.name} est  {stock_quant}."
            if stock_quant.quantity < qty_to_deduct:
                _logger.info(
                    f"Attention: Stock insuffisant pour {component.name} dans l'emplacement "
                    f"{preferred_location.name}. Disponible: {stock_quant.quantity}, "
                    f"Requis: {qty_to_deduct}. Le stock deviendra négatif."
                )
                warnings.append(
                    f"Attention: Stock insuffisant pour {component.name} dans l'emplacement "
                    f"{preferred_location.name}. Disponible: {stock_quant.quantity}, "
                    f"Requis: {qty_to_deduct}. Le stock deviendra négatif."
                )
            new_qty = stock_quant.quantity - qty_to_deduct
            stock_quant.sudo().write({'quantity': new_qty})
            _logger.info(
                f"Déduit {qty_to_deduct} de {component.name} dans l'emplacement {preferred_location.name}. "
                f"Nouveau stock: {new_qty}"
            )
        else:
            stock_quant = self.env['stock.quant'].search([
                ('product_id', '=', component.id),
                ('location_id.usage', '=', 'internal')
            ], limit=1)

            if not stock_quant:
                default_location = self.env['stock.location'].search(
                    [('usage', '=', 'internal')], limit=1)
                stock_quant = self._get_or_create_stock_quant(component, default_location)

            if stock_quant.quantity < qty_to_deduct:
                warnings.append(
                    f"Attention: Stock insuffisant pour {component.name} dans l'emplacement "
                    f"{stock_quant.location_id.name}. Disponible: {stock_quant.quantity}, "
                    f"Requis: {qty_to_deduct}. Le stock deviendra négatif."
                )
            new_qty = stock_quant.quantity - qty_to_deduct
            stock_quant.sudo().write({'quantity': new_qty})
            _logger.info(
                f"Déduit {qty_to_deduct} de {component.name} dans l'emplacement {preferred_location.name}. "
                f"Nouveau stock: {new_qty}"
            )

    def _get_or_create_stock_quant(self, product, location):
        """
        Retrieve or create a stock quant for a given product and location.
        """
        stock_quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id)
        ], limit=1)
        _logger.info(
            f"stock_quant {stock_quant} "
        )

        if not stock_quant:
            stock_quant = self.env['stock.quant'].sudo().create({
                'product_id': product.id,
                'location_id': location.id,
                'quantity': 0
            })
            _logger.info(
                f"new stock_quant {stock_quant} "
            )
        return stock_quant

    def process_bom_recursively(self, product, quantity, warnings, override_location=None):
        """
        Recursively process the BOM and decrement the stock of components at all levels.
        """
        # For the first call (final product), check if it has a preferred location
        if override_location is None:
            final_product_location = product.product_tmpl_id.pos_preferred_location_id
            if final_product_location:
                override_location = final_product_location
                print("final_product_location", final_product_location)
                _logger.info(
                    f"Produit final {product.name} a un emplacement préféré: {override_location.name}. "
                    f"Utilisation prioritaire de cet emplacement pour tous les composants."
                )

        _logger.info(
            f"Traitement du produit {product.name} (type: {product.type}) - "
            f"Override location: {override_location.name if override_location else 'None'}"
        )

        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id)
        ], limit=1)

        if bom:
            for bom_line in bom.bom_line_ids:
                component = bom_line.product_id
                qty_to_deduct = bom_line.product_qty * quantity

                # Checks if the component itself has a BOM
                sub_bom = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', component.product_tmpl_id.id)
                ], limit=1)

                if sub_bom:
                    # If the component has a sub-BOM, recursive call
                    _logger.info(
                        f"Traitement de la sous-nomenclature pour {component.name}"
                    )
                    self.process_bom_recursively(component, qty_to_deduct, warnings, override_location)
                else:
                    # Basic component, deduction from stock
                    _logger.info(
                        f"DÉBOGAGE: Composant de base {component.name}, override_location = {override_location.name if override_location else 'None'}")

                    if override_location:
                        # If a priority location(override_location) exists (of the final product), use it
                        _logger.info(
                            f"APPEL _decrement_from_specific_location pour {component.name} dans {override_location.name}"
                        )
                        self._decrement_from_specific_location(component, qty_to_deduct, override_location, warnings)
                    else:
                        # Else,use normal logic with the preferred component location
                        _logger.info(
                            f"APPEL _decrement_component_stock pour {component.name}"
                        )
                        self._decrement_component_stock(component, qty_to_deduct, warnings)
    def _decrement_from_specific_location(self, component, qty_to_deduct, location, warnings):
        """
        Décrémenter le stock d'un composant depuis un emplacement spécifique.
        """
        stock_quant = self._get_or_create_stock_quant(component, location)

        if stock_quant.quantity < qty_to_deduct:
            warning_msg = (
                f"Attention: Stock insuffisant pour {component.name} dans l'emplacement "
                f"du produit final {location.name}. Disponible: {stock_quant.quantity}, "
                f"Requis: {qty_to_deduct}. Le stock deviendra négatif."
            )
            _logger.info(warning_msg)
            warnings.append(warning_msg)

        new_qty = stock_quant.quantity - qty_to_deduct
        stock_quant.sudo().write({'quantity': new_qty})
        _logger.info(
            f"Déduit {qty_to_deduct} de {component.name} depuis l'emplacement du produit final {location.name}. "
            f"Nouveau stock: {new_qty}"
        )

    def _decrement_bom_components(self):
        """
        Main method to decrement components from BOM.
        """
        print("here in _decrement_bom_components")
        self.ensure_one()
        warnings = []

        for order in self._get_closed_orders():
            for line in order.lines:
                product = line.product_id
                _logger.info(
                    f"Pour le produit {product.name} (type: {product.type}) avec quantité {line.qty}"
                )

                # Récupérer l'emplacement préféré du produit final
                product_location = product.product_tmpl_id.pos_preferred_location_id
                if product_location:
                    _logger.info(
                        f"Le produit {product.name} a un emplacement préféré défini: {product_location.name}"
                    )
                else:
                    _logger.info(
                        f"Le produit {product.name} n'a pas d'emplacement préféré défini"
                    )

                # Passer l'emplacement préféré du produit final comme override_location
                self.process_bom_recursively(product, line.qty, warnings, override_location=product_location)

        if warnings:
            warning_message = "Avertissements de stock :\n\n" + "\n".join(warnings)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Attention - Stock Insuffisant',
                    'message': warning_message,
                    'sticky': True,
                    'type': 'warning',
                }
            }

        return True

    def check_component_stock_recursively(self, product, quantity, processed_products=None, path='',
                                          override_location=None):
        """
        Recursively checks the available stock for all components of a product,
        including subcomponents, while handling nested BOMs.

        Args:
            product: The product to check
            quantity: The required quantity
            processed_products: Set of already processed product IDs to avoid infinite loops
            path: String representing the path of components (for error messages)
            override_location: Location to check stock in (from final product)
        """
        if processed_products is None:
            processed_products = set()

        stock_errors = []

        # For the first call (final product), check if it has a preferred location
        if override_location is None:
            final_product_location = product.product_tmpl_id.pos_preferred_location_id
            if final_product_location:
                override_location = final_product_location
                _logger.info(
                    f"Vérification du stock: Produit final {product.name} a un emplacement préféré: {override_location.name}. "
                    f"Vérification prioritaire dans cet emplacement pour tous les composants."
                )

        # Prevent infinite recursion
        if product.id in processed_products:
            return stock_errors
        processed_products.add(product.id)

        # Check if product has a BOM
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id)
        ], limit=1)

        if bom:
            # Product has a BOM, check its components
            for bom_line in bom.bom_line_ids:
                component = bom_line.product_id
                qty_to_check = bom_line.product_qty * quantity

                component_path = f"{path} > {component.name}" if path else component.name

                # Check if component has its own BOM
                sub_bom = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', component.product_tmpl_id.id)
                ], limit=1)

                if sub_bom and component.id not in processed_products:
                    # Component has its own BOM and hasn't been processed
                    sub_errors = self.check_component_stock_recursively(
                        component,
                        qty_to_check,
                        processed_products.copy(),
                        component_path,
                        override_location
                    )
                    stock_errors.extend(sub_errors)
                else:
                    # Component is a raw material or has already been processed
                    stock_errors.extend(self._check_component_stock_level(
                        component,
                        qty_to_check,
                        component_path,
                        override_location
                    ))
        else:
            stock_errors.extend(self._check_component_stock_level(
                product,
                quantity,
                path or product.name,
                override_location
            ))

        return stock_errors

    def _check_component_stock_level(self, component, qty_to_check, component_path, override_location=None):
        """
        Checks the stock level for a single component.

        Args:
            component: The component product to check
            qty_to_check: Required quantity
            component_path: Path string for error message
            override_location: Location to check stock in (from final product)
        """
        errors = []

        # If an override location (of the final product) exist, use it as a priority
        if override_location:
            # Get all valid stock quants in the override location
            stock_quants = self.env['stock.quant'].search([
                ('product_id', '=', component.id),
                ('location_id', '=', override_location.id),
            ])

            # Calculate total available quantity
            available_qty = sum(quant.quantity for quant in stock_quants if quant.quantity > 0)

            if available_qty < qty_to_check:
                error_msg = (
                    f"Stock insuffisant pour {component_path} dans l'emplacement "
                    f"du produit final {override_location.name}! Disponible: {available_qty}, "
                    f"Requis: {qty_to_check}"
                )
                errors.append(error_msg)
        else:
            # Else use the preferred location of the component
            preferred_location = component.product_tmpl_id.pos_preferred_location_id

            if preferred_location:
                # Get all valid stock quants
                stock_quants = self.env['stock.quant'].search([
                    ('product_id', '=', component.id),
                    ('location_id', '=', preferred_location.id),
                ])

                # Calculate total available quantity
                available_qty = sum(quant.quantity for quant in stock_quants if quant.quantity > 0)

                if available_qty < qty_to_check:
                    error_msg = (
                        f"Stock insuffisant pour {component_path} dans l'emplacement "
                        f"{preferred_location.name}! Disponible: {available_qty}, "
                        f"Requis: {qty_to_check}"
                    )
                    errors.append(error_msg)

        return errors

    def _aggregate_requirements(self, product, quantity, requirements=None, processed_products=None,
                                override_location=None):
        """
        Aggregates the total required quantity for each component across all BOMs.

        Args:
            product: The product to analyze
            quantity: Required quantity
            requirements: Dict to store requirements {component_id: {'qty': float, 'paths': list}}
            processed_products: Set to prevent infinite loops
            override_location: Location to check stock in (from final product)
        """
        if requirements is None:
            requirements = {}
        if processed_products is None:
            processed_products = set()

        # For the first call (final product), check if it has a preferred location
        if override_location is None:
            final_product_location = product.product_tmpl_id.pos_preferred_location_id
            if final_product_location:
                override_location = final_product_location

        if product.id in processed_products:
            return requirements
        processed_products.add(product.id)

        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id)
        ], limit=1)

        if bom:
            for bom_line in bom.bom_line_ids:
                component = bom_line.product_id
                qty_required = bom_line.product_qty * quantity

                sub_bom = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', component.product_tmpl_id.id)
                ], limit=1)

                if sub_bom and component.id not in processed_products:
                    self._aggregate_requirements(
                        component,
                        qty_required,
                        requirements,
                        processed_products.copy(),
                        override_location
                    )
                else:
                    component_key = f"{component.id}_{override_location.id if override_location else 0}"
                    if component_key in requirements:
                        requirements[component_key]['qty'] += qty_required
                    else:
                        requirements[component_key] = {
                            'component': component,
                            'qty': qty_required,
                            'location': override_location,
                            'paths': set()
                        }

        return requirements

    def check_stock_availability(self):
        """Check if there are any potential stock issues before closing the session."""
        installed_modules = self.env['ir.module.module'].sudo().search([
            ('name', 'in', ['mrp', 'stock']),
            ('state', '=', 'installed')
        ])

        installed_modules_names = installed_modules.mapped('name')
        _logger.info(f"installed_modules_names {installed_modules_names}")

        stock_errors = []
        if 'mrp' in installed_modules_names and 'stock' in installed_modules_names:
            total_requirements = {}

            for order in self._get_closed_orders():
                for line in order.lines:
                    product = line.product_id
                    # check in the preferred location of the component
                    final_product_location = product.product_tmpl_id.pos_preferred_location_id
                    requirements = self._aggregate_requirements(product, line.qty,
                                                                override_location=final_product_location)

                    # Merge requirements
                    for comp_key, req_data in requirements.items():
                        if comp_key in total_requirements:
                            total_requirements[comp_key]['qty'] += req_data['qty']
                        else:
                            total_requirements[comp_key] = req_data

            # Check stock levels
            for req_data in total_requirements.values():
                component = req_data['component']
                qty_required = req_data['qty']
                override_location = req_data.get('location')
                print("le composant ",component.name)
                print("Emplacement",override_location.name)

                if override_location:
                    # Check in the final product location
                    stock_quants = self.env['stock.quant'].search([
                        ('product_id', '=', component.id),
                        ('location_id', '=', override_location.id),
                    ])

                    available_qty = sum(quant.quantity for quant in stock_quants if quant.quantity > 0)

                    if available_qty < qty_required:
                        error_msg = (
                            f"Stock insuffisant pour {component.name} dans l'emplacement "
                            f"du produit final {override_location.name}! "
                            f"Disponible: {available_qty}, "
                            f"Requis total: {round(qty_required, 3)}"
                        )
                        stock_errors.append(error_msg)
                else:
                    # else check in the preferred location of the component
                    preferred_location = component.product_tmpl_id.pos_preferred_location_id

                    if preferred_location:
                        stock_quants = self.env['stock.quant'].search([
                            ('product_id', '=', component.id),
                            ('location_id', '=', preferred_location.id),
                        ])

                        available_qty = sum(quant.quantity for quant in stock_quants if quant.quantity > 0)

                        if available_qty < qty_required:
                            error_msg = (
                                f"Stock insuffisant pour {component.name} dans l'emplacement "
                                f"{preferred_location.name}! "
                                f"Disponible: {available_qty}, "
                                f"Requis total: {round(qty_required, 3)}"
                            )
                            stock_errors.append(error_msg)

            return {
                'success': len(stock_errors) == 0,
                'errors': stock_errors
            }
        return {
            'success': len(stock_errors) == 0,
            'errors': stock_errors
        }
