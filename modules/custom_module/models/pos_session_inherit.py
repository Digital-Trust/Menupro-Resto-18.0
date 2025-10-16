from odoo import fields, models, api
import logging

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'
    ticket_number = fields.Integer(string='Ticket Number', help='A  number that is incremented with each order',
                                   default=1)

    def _load_pos_data_fields(self, config_id):
        result = super()._load_pos_data_fields(config_id)
        pos_order = self.env['pos.order']
        ticket_number = pos_order.get_today_ticket_number()
        result.append('ticket_number')
        return result

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        installed_modules = self.env['ir.module.module'].sudo().search([
            ('name', 'in', ['mrp', 'stock']),
            ('state', '=', 'installed')
        ])

        installed_modules_names = installed_modules.mapped('name')

        if 'mrp' in installed_modules_names and 'stock' in installed_modules_names:
            self._decrement_bom_components()

        return super().close_session_from_ui(bank_payment_method_diff_pairs)

    def _decrement_component_stock(self, component, qty_to_deduct, warnings):
        """
        Decrement the stock of a component in its preferred location
            or in the first available internal location.
        """

        if not component.is_storable:
            _logger.info(
                f"Le produit {component.name} n'est pas stockable (is_storable=False). Ignoré."
            )
            return
        preferred_location = component.product_tmpl_id.pos_preferred_location_id

        if preferred_location:
            stock_quant = self._get_or_create_stock_quant(component, preferred_location)
            if not stock_quant:  # ✅ Gérer le cas où le quant n'est pas créé
                return
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
                f"Déduit {qty_to_deduct} de {component.name} dans l'emplacement {stock_quant.location_id.name}. "
                f"Nouveau stock: {new_qty}"
            )

    def _get_or_create_stock_quant(self, product, location):
        """
        Retrieve or create a stock quant for a given product and location.
        """
        if not product.is_storable:
            _logger.warning(
                f"Impossible de créer des quants pour des produits non stockables. "
                f"Produit: {product.name} (is_storable=False)"
            )
            return False
        stock_quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id)
        ], limit=1)

        if not stock_quant:
            stock_quant = self.env['stock.quant'].sudo().create({
                'product_id': product.id,
                'location_id': location.id,
                'quantity': 0
            })
            _logger.info(f"Nouveau stock_quant créé pour {product.name}")

        return stock_quant

    def process_bom_recursively(self, product, quantity, warnings, override_location=None, bom_dict=None):
        """
        Recursively process the BOM and decrement the stock.
        For 'normal' type BOMs, deduct the finished product instead of components.
        
        :param bom_dict: Optional pre-fetched dictionary of BOMs {product_tmpl_id: bom}
        """

        if not product.is_storable:
            _logger.info(
                f"Le produit {product.name} n'est pas stockable (is_storable=False). "
                f"Aucune déduction de stock nécessaire."
            )
            return
        if override_location is None:
            final_product_location = product.product_tmpl_id.pos_preferred_location_id
            if final_product_location:
                override_location = final_product_location
                _logger.info(
                    f"Produit final {product.name} a un emplacement préféré: {override_location.name}. "
                    f"Utilisation prioritaire de cet emplacement pour tous les composants."
                )

        # Use pre-fetched BOM if available, otherwise search
        if bom_dict is not None:
            bom = bom_dict.get(product.product_tmpl_id.id)
        else:
            bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id)
            ], limit=1)

        if bom:
            # Vérifier le type de nomenclature
            if bom.type == 'normal':
                # Pour une nomenclature normale, déduire le produit fini lui-même
                _logger.info(
                    f"Nomenclature de type 'normal' détectée pour {product.name}. "
                    f"Déduction du produit fini au lieu des composants."
                )

                if override_location:
                    self._decrement_from_specific_location(product, quantity, override_location, warnings)
                else:
                    self._decrement_component_stock(product, quantity, warnings)
            else:
                # Pour les autres types de nomenclature (phantom, etc.), déduire les composants
                _logger.info(
                    f"Nomenclature de type '{bom.type}' détectée pour {product.name}. "
                    f"Déduction des composants."
                )

                component_tmpl_ids = bom.bom_line_ids.mapped('product_id.product_tmpl_id.id')
                sub_boms_dict = {}
                if component_tmpl_ids:
                    sub_boms = self.env['mrp.bom'].search([
                        ('product_tmpl_id', 'in', component_tmpl_ids)
                    ])
                    # Create a dict for quick lookup
                    for sub_bom in sub_boms:
                        sub_boms_dict[sub_bom.product_tmpl_id.id] = sub_bom

                for bom_line in bom.bom_line_ids:
                    component = bom_line.product_id
                    qty_to_deduct = bom_line.product_qty * quantity

                    sub_bom = sub_boms_dict.get(component.product_tmpl_id.id)

                    if sub_bom:
                        # Appel récursif pour le sous-composant
                        _logger.info(f"Traitement de la sous-nomenclature pour {component.name}")
                        self.process_bom_recursively(component, qty_to_deduct, warnings, override_location, bom_dict)
                    else:
                        # Composant de base, déduction du stock
                        if override_location:
                            self._decrement_from_specific_location(component, qty_to_deduct, override_location,
                                                                   warnings)
                        else:
                            self._decrement_component_stock(component, qty_to_deduct, warnings)
        else:
            # Pas de nomenclature, déduire le produit directement
            _logger.info(f"Pas de nomenclature pour {product.name}, déduction du produit")
            if override_location:
                self._decrement_from_specific_location(product, quantity, override_location, warnings)
            else:
                self._decrement_component_stock(product, quantity, warnings)

    def _decrement_from_specific_location(self, component, qty_to_deduct, location, warnings):
        """
        Décrémenter le stock d'un composant depuis un emplacement spécifique.
        """

        if not component.is_storable:
            _logger.info(
                f"Le composant {component.name} n'est pas stockable. Ignoré."
            )
            return
        stock_quant = self._get_or_create_stock_quant(component, location)
        if not stock_quant:  # ✅ Gérer le retour False
            return

        if stock_quant.quantity < qty_to_deduct:
            warning_msg = (
                f"Attention: Stock insuffisant pour {component.name} dans l'emplacement "
                f"{location.name}. Disponible: {stock_quant.quantity}, "
                f"Requis: {qty_to_deduct}. Le stock deviendra négatif."
            )
            _logger.info(warning_msg)
            warnings.append(warning_msg)

        new_qty = stock_quant.quantity - qty_to_deduct
        stock_quant.sudo().write({'quantity': new_qty})
        _logger.info(
            f"Déduit {qty_to_deduct} de {component.name} depuis l'emplacement {location.name}. "
            f"Nouveau stock: {new_qty}"
        )

    def _decrement_bom_components(self):
        """
        Main method to decrement components from BOM.
        """
        _logger.info("Début de la déduction des composants de nomenclature")
        self.ensure_one()
        warnings = []

        # Batch optimization: Collect all lines first
        all_lines = []
        for order in self._get_closed_orders():
            all_lines.extend(order.lines)
        
        if not all_lines:
            return True

        # Pre-fetch all products and their templates to reduce queries
        products = self.env['product.product'].browse([line.product_id.id for line in all_lines])
        product_tmpl_ids = products.mapped('product_tmpl_id.id')
        
        # Pre-fetch all BOMs for these products in one query
        all_boms = self.env['mrp.bom'].search([
            ('product_tmpl_id', 'in', product_tmpl_ids)
        ])
        bom_dict = {bom.product_tmpl_id.id: bom for bom in all_boms}
        
        # Group lines by product to aggregate quantities
        product_qty_map = {}
        for line in all_lines:
            product = line.product_id
            product_location = product.product_tmpl_id.pos_preferred_location_id
            
            key = (product.id, product_location.id if product_location else None)
            if key not in product_qty_map:
                product_qty_map[key] = {
                    'product': product,
                    'quantity': 0,
                    'location': product_location
                }
            product_qty_map[key]['quantity'] += line.qty
            
            _logger.info(
                f"Traitement du produit {product.name} (type: {product.type}) avec quantité {line.qty}"
            )

        # Process each unique product-location combination
        for key, data in product_qty_map.items():
            product = data['product']
            quantity = data['quantity']
            product_location = data['location']
            
            self.process_bom_recursively(
                product, 
                quantity, 
                warnings, 
                override_location=product_location,
                bom_dict=bom_dict
            )

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
        Recursively checks the available stock for all components of a product.
        For 'normal' type BOMs, checks the finished product stock instead of components.
        """
        if processed_products is None:
            processed_products = set()

        stock_errors = []
        if not product.is_storable:
            _logger.info(
                f"Le produit {product.name} n'est pas stockable. "
                f"Vérification de stock ignorée."
            )
            return stock_errors

        if override_location is None:
            final_product_location = product.product_tmpl_id.pos_preferred_location_id
            if final_product_location:
                override_location = final_product_location

        if product.id in processed_products:
            return stock_errors
        processed_products.add(product.id)

        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id)
        ], limit=1)

        if bom:
            if bom.type == 'normal':
                # Pour une nomenclature normale, vérifier le stock du produit fini
                _logger.info(f"Vérification du stock pour produit fini avec nomenclature normale: {product.name}")
                stock_errors.extend(self._check_component_stock_level(
                    product,
                    quantity,
                    path or product.name,
                    override_location
                ))
            else:
                # Pour les autres types, vérifier les composants
                # Optimized: Pre-fetch all sub-BOMs to avoid N+1 queries
                component_tmpl_ids = bom.bom_line_ids.mapped('product_id.product_tmpl_id.id')
                sub_boms_dict = {}
                if component_tmpl_ids:
                    sub_boms = self.env['mrp.bom'].search([
                        ('product_tmpl_id', 'in', component_tmpl_ids)
                    ])
                    for sub_bom in sub_boms:
                        sub_boms_dict[sub_bom.product_tmpl_id.id] = sub_bom

                for bom_line in bom.bom_line_ids:
                    component = bom_line.product_id
                    qty_to_check = bom_line.product_qty * quantity
                    component_path = f"{path} > {component.name}" if path else component.name

                    sub_bom = sub_boms_dict.get(component.product_tmpl_id.id)

                    if sub_bom and component.id not in processed_products:
                        sub_errors = self.check_component_stock_recursively(
                            component,
                            qty_to_check,
                            processed_products.copy(),
                            component_path,
                            override_location
                        )
                        stock_errors.extend(sub_errors)
                    else:
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
        """
        errors = []
        if not component.is_storable:
            _logger.info(
                f"Le composant {component.name} n'est pas stockable. "
                f"Vérification de stock ignorée."
            )
            return errors

        if override_location:
            stock_quants = self.env['stock.quant'].search([
                ('product_id', '=', component.id),
                ('location_id', '=', override_location.id),
            ])

            available_qty = sum(quant.quantity for quant in stock_quants if quant.quantity > 0)

            if available_qty < qty_to_check:
                error_msg = (
                    f"Stock insuffisant pour {component_path} dans l'emplacement "
                    f"{override_location.name}! Disponible: {available_qty}, "
                    f"Requis: {qty_to_check}"
                )
                errors.append(error_msg)
        else:
            preferred_location = component.product_tmpl_id.pos_preferred_location_id

            if preferred_location:
                stock_quants = self.env['stock.quant'].search([
                    ('product_id', '=', component.id),
                    ('location_id', '=', preferred_location.id),
                ])

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
        Aggregates the total required quantity for each component.
        For 'normal' type BOMs, aggregates the finished product instead of components.
        """
        if requirements is None:
            requirements = {}
        if processed_products is None:
            processed_products = set()

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
            if bom.type == 'normal':
                # Pour une nomenclature normale, agréger le produit fini
                component_key = f"{product.id}_{override_location.id if override_location else 0}"
                if component_key in requirements:
                    requirements[component_key]['qty'] += quantity
                else:
                    requirements[component_key] = {
                        'component': product,
                        'qty': quantity,
                        'location': override_location,
                        'paths': set()
                    }
            else:
                # Pour les autres types, agréger les composants
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
        stock_errors = []

        if 'mrp' in installed_modules_names and 'stock' in installed_modules_names:
            total_requirements = {}

            for order in self._get_closed_orders():
                for line in order.lines:
                    product = line.product_id
                    final_product_location = product.product_tmpl_id.pos_preferred_location_id
                    requirements = self._aggregate_requirements(product, line.qty,
                                                                override_location=final_product_location)

                    for comp_key, req_data in requirements.items():
                        if comp_key in total_requirements:
                            total_requirements[comp_key]['qty'] += req_data['qty']
                        else:
                            total_requirements[comp_key] = req_data

            for req_data in total_requirements.values():
                component = req_data['component']
                qty_required = req_data['qty']
                override_location = req_data.get('location')

                if override_location:
                    stock_quants = self.env['stock.quant'].search([
                        ('product_id', '=', component.id),
                        ('location_id', '=', override_location.id),
                    ])

                    available_qty = sum(quant.quantity for quant in stock_quants if quant.quantity > 0)

                    if available_qty < qty_required:
                        error_msg = (
                            f"Stock insuffisant pour {component.name} dans l'emplacement "
                            f"{override_location.name}! "
                            f"Disponible: {available_qty}, "
                            f"Requis total: {round(qty_required, 3)}"
                        )
                        stock_errors.append(error_msg)
                else:
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