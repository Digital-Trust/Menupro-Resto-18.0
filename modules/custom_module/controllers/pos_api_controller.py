# -*- coding: utf-8 -*-
import logging
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PosApiController(http.Controller):

    @staticmethod
    def _authenticate_request(params):
        """
        Authentifier la requête avec api_key et retourner l'utilisateur correspondant
        """
        api_key = params.get('api_key')
        if not api_key:
            return None, {"error": "api_key is required", "code": "MISSING_API_KEY"}

        # Option 1: Recherche par champ api_key sur res.users (si vous l'avez)
        try:
            user = request.env['res.users'].sudo().search([
                ('api_key', '=', api_key),
                ('active', '=', True)
            ], limit=1)
        except Exception:
            user = False

        # Option 2: Si pas de champ api_key, utiliser une table séparée
        if not user:
            try:
                token_record = request.env['api.token'].sudo().search([
                    ('token', '=', api_key),
                    ('active', '=', True),
                    ('expiry_date', '>', fields.Datetime.now())
                ], limit=1)
                if token_record:
                    user = token_record.user_id
            except Exception:
                pass

        # Option 3: Authentification basique pour test (à supprimer en production)
        if not user and api_key == 'test_key':
            user = request.env['res.users'].sudo().search([('login', '=', 'admin')], limit=1)

        if not user:
            return None, {"error": "Invalid or expired api_key", "code": "INVALID_API_KEY"}

        return user, None

    def _check_pos_access(self, user, pos_config, operation='read'):
        """
        Vérifier l'accès à une configuration POS avec l'utilisateur donné
        Mise à jour pour Odoo 18.0 - utilise check_access() au lieu des méthodes dépréciées
        """
        try:
            # Créer un environnement avec l'utilisateur spécifique
            env = request.env(user=user.id)
            pos_config_with_user = env['pos.config'].browse(pos_config.id)

            # Vérifier les droits d'accès avec la nouvelle méthode Odoo 18.
            pos_config_with_user.check_access(operation)
            return True
        except AccessError:
            return False
        except Exception as e:
            _logger.warning(f"Erreur vérification accès POS: {e}")
            return False

    @http.route('/pos_session_open', type='json', auth='none', methods=['POST'], csrf=False)
    def open_session(self, **kwargs):
        """
        Ouvrir une session POS avec authentification
        """
        try:
            user, error = self._authenticate_request(kwargs)
            if error:
                return error

            config_id = kwargs.get('config_id')
            cash_amount = float(kwargs.get('cash_amount', 0.0))
            opening_notes = kwargs.get('notes', '')

            if not config_id:
                return {"success": False, "error": "config_id is required", "error_code": "MISSING_CONFIG_ID"}

            try:
                config_id = int(config_id)
                pos_config = request.env['pos.config'].sudo().browse(config_id)
                if not pos_config.exists():
                    return {"success": False, "error": f"POS config {config_id} not found",
                            "error_code": "CONFIG_NOT_FOUND"}

                # Vérifier l'accès avec l'utilisateur authentifié
                if not self._check_pos_access(user, pos_config, 'read'):
                    return {"success": False, "error": "Access denied to this POS configuration",
                            "error_code": "ACCESS_DENIED"}

            except (ValueError, TypeError):
                return {"success": False, "error": f"Invalid config_id format: {config_id}",
                        "error_code": "INVALID_CONFIG_ID"}

            # Créer un environnement avec l'utilisateur authentifié
            env = request.env(user=user.id)

            # Vérifier s'il y a déjà une session ouverte
            existing_session = env['pos.session'].search([
                ('config_id', '=', config_id),
                ('state', '!=', 'closed'),
                ('rescue', '=', False)
            ], limit=1)

            if existing_session:
                if existing_session.state == 'closing_control':
                    return {"success": False, "error": "Session is currently being closed",
                            "error_code": "CLOSING_IN_PROGRESS"}

                # Si la session existe mais n'est pas ouverte, on continue le processus
                session = existing_session
            else:
                # Créer une nouvelle session
                try:
                    session = env['pos.session'].create({
                        'config_id': config_id,
                        'user_id': user.id,
                    })
                    _logger.info(f"Nouvelle session créée: {session.id} par {user.name}")
                except Exception as e:
                    _logger.error(f"Erreur création session: {e}")
                    return {"success": False, "error": f"Failed to create session: {str(e)}",
                            "error_code": "CREATE_FAILED"}

            # Processus d'ouverture selon l'état de la session
            try:
                if session.state == 'opening_control':
                    # La méthode set_opening_control existe dans le code fourni
                    session.set_opening_control(cash_amount, opening_notes)
                    _logger.info(f"Session {session.id} ouverte avec montant initial: {cash_amount}")
                elif session.state != 'opened':
                    # Fallback si la session n'est pas dans l'état attendu
                    session.action_pos_session_open()
                    _logger.info(f"Session {session.id} ouverte via action_pos_session_open")

            except Exception as e:
                _logger.error(f"Erreur ouverture session {session.id}: {e}")
                return {"success": False, "error": f"Failed to open session: {str(e)}", "error_code": "OPEN_FAILED"}

            return {
                "success": True,
                "session_id": session.id,
                "session_name": session.name,
                "state": session.state,
                "config_id": session.config_id.id,
                "config_name": session.config_id.name,
                "user_id": session.user_id.id,
                "user_name": session.user_id.name,
                "start_at": str(session.start_at) if session.start_at else None,
                "cash_register_balance_start": session.cash_register_balance_start,
            }

        except Exception as e:
            _logger.error(f"Erreur générale ouverture session POS: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    @http.route('/pos_session_close', type='json', auth='none', methods=['POST'], csrf=False)
    def close_session(self, **kwargs):
        """
        Fermer une session POS avec authentification
        """
        try:
            user, error = self._authenticate_request(kwargs)
            if error:
                return error

            session_id = kwargs.get('session_id')
            cash_amount = kwargs.get('cash_amount')  # Montant final de caisse
            closing_notes = kwargs.get('notes', '')

            if not session_id:
                return {"success": False, "error": "session_id is required", "error_code": "MISSING_SESSION_ID"}

            try:
                session_id = int(session_id)
            except (ValueError, TypeError):
                return {"success": False, "error": f"Invalid session_id format: {session_id}",
                        "error_code": "INVALID_SESSION_ID"}

            # Créer un environnement avec l'utilisateur authentifié
            env = request.env(user=user.id)
            session = env['pos.session'].browse(session_id)

            if not session.exists():
                return {"success": False, "error": f"Session {session_id} not found", "error_code": "SESSION_NOT_FOUND"}

            # Vérifier l'accès
            if not self._check_pos_access(user, session.config_id, 'write'):
                return {"success": False, "error": "Access denied to close this session", "error_code": "ACCESS_DENIED"}

            # Vérifier l'état de la session
            if session.state == 'closed':
                return {"success": False, "error": "Session is already closed", "error_code": "ALREADY_CLOSED"}

            try:
                # Processus de fermeture selon l'état
                if session.state == 'opened':
                    # Étape 1: Passer en closing_control
                    session.update_closing_control_state_session(closing_notes)

                    # Si un montant de caisse final est fourni, l'enregistrer
                    if cash_amount is not None:
                        result = session.post_closing_cash_details(float(cash_amount))
                        if not result.get('successful', True):
                            return {"success": False, "error": result.get('message', 'Failed to post cash details'),
                                    "error_code": "CASH_DETAILS_FAILED"}

                    # Fermer définitivement
                    close_result = session.close_session_from_ui()
                    if not close_result.get('successful', True):
                        return {"success": False, "error": close_result.get('message', 'Failed to close session'),
                                "error_code": "CLOSE_FAILED"}

                elif session.state == 'closing_control':
                    # La session est déjà en cours de fermeture, finaliser
                    if cash_amount is not None:
                        result = session.post_closing_cash_details(float(cash_amount))
                        if not result.get('successful', True):
                            return {"success": False, "error": result.get('message', 'Failed to post cash details'),
                                    "error_code": "CASH_DETAILS_FAILED"}

                    close_result = session.close_session_from_ui()
                    if not close_result.get('successful', True):
                        return {"success": False, "error": close_result.get('message', 'Failed to close session'),
                                "error_code": "CLOSE_FAILED"}

                else:
                    return {"success": False, "error": f"Cannot close session in state: {session.state}",
                            "error_code": "INVALID_STATE"}

                _logger.info(f"Session {session.id} fermée par {user.name}")

            except UserError as ue:
                _logger.warning(f"Erreur utilisateur fermeture session {session.id}: {ue}")
                return {"success": False, "error": str(ue), "error_code": "USER_ERROR"}
            except Exception as e:
                _logger.error(f"Erreur fermeture session {session.id}: {e}")
                return {"success": False, "error": f"Failed to close session: {str(e)}", "error_code": "CLOSE_ERROR"}


            session = env['pos.session'].browse(session_id)

            return {
                "success": True,
                "session_id": session.id,
                "session_name": session.name,
                "state": session.state,
                "user": user.name,
                "closed_by": user.name,
                "start_at": str(session.start_at) if session.start_at else None,
                "stop_at": str(session.stop_at) if session.stop_at else None,
                "cash_register_balance_start": session.cash_register_balance_start,
                "cash_register_balance_end_real": session.cash_register_balance_end_real,
            }

        except Exception as e:
            _logger.error(f"Erreur générale fermeture session POS: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    @http.route('/pos_session_status', type='json', auth='none', methods=['POST'], csrf=False)
    def session_status(self, **kwargs):
        """
        Vérifier le statut d'une session POS
        """
        try:
            user, error = self._authenticate_request(kwargs)
            if error:
                return error

            config_id = kwargs.get('config_id')
            session_id = kwargs.get('session_id')

            if not config_id and not session_id:
                return {"success": False, "error": "config_id or session_id is required",
                        "error_code": "MISSING_PARAMETERS"}

            env = request.env(user=user.id)

            if session_id:
                # Statut d'une session spécifique
                try:
                    session_id = int(session_id)
                    session = env['pos.session'].browse(session_id)
                    if not session.exists():
                        return {"success": False, "error": f"Session {session_id} not found",
                                "error_code": "SESSION_NOT_FOUND"}

                    return {
                        "success": True,
                        "session": {
                            "id": session.id,
                            "name": session.name,
                            "state": session.state,
                            "config_id": session.config_id.id,
                            "config_name": session.config_id.name,
                            "user_name": session.user_id.name,
                            "start_at": str(session.start_at) if session.start_at else None,
                            "stop_at": str(session.stop_at) if session.stop_at else None,
                            "cash_register_balance_start": session.cash_register_balance_start,
                            "cash_register_balance_end_real": session.cash_register_balance_end_real,
                            "order_count": session.order_count,
                        }
                    }
                except (ValueError, TypeError):
                    return {"success": False, "error": f"Invalid session_id format: {session_id}",
                            "error_code": "INVALID_SESSION_ID"}

            else:
                # Statut des sessions par config_id
                try:
                    config_id = int(config_id)
                    pos_config = env['pos.config'].browse(config_id)
                    if not pos_config.exists():
                        return {"success": False, "error": f"POS config {config_id} not found",
                                "error_code": "CONFIG_NOT_FOUND"}

                    # Rechercher toutes les sessions de cette configuration
                    sessions = env['pos.session'].search([
                        ('config_id', '=', config_id)
                    ], order='start_at desc')

                    open_sessions = sessions.filtered(lambda s: s.state != 'closed')
                    closed_sessions = sessions.filtered(lambda s: s.state == 'closed')[:5]  # 5 dernières

                    return {
                        "success": True,
                        "config_name": pos_config.name,
                        "config_id": pos_config.id,
                        "open_sessions": [{
                            "id": s.id,
                            "name": s.name,
                            "state": s.state,
                            "user_name": s.user_id.name,
                            "start_at": str(s.start_at) if s.start_at else None,
                            "cash_register_balance_start": s.cash_register_balance_start,
                            "order_count": s.order_count,
                        } for s in open_sessions],
                        "recent_closed_sessions": [{
                            "id": s.id,
                            "name": s.name,
                            "state": s.state,
                            "user_name": s.user_id.name,
                            "start_at": str(s.start_at) if s.start_at else None,
                            "stop_at": str(s.stop_at) if s.stop_at else None,
                        } for s in closed_sessions]
                    }
                except (ValueError, TypeError):
                    return {"success": False, "error": f"Invalid config_id format: {config_id}",
                            "error_code": "INVALID_CONFIG_ID"}

        except Exception as e:
            _logger.error(f"Erreur status session POS: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}