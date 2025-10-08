"""Input validation and sanitization utilities for controllers."""
import re
import html
import logging
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InputValidator:
    """Validator for controller inputs."""
    
    @staticmethod
    def validate_required_fields(data, required_fields):
        """
        Validate that all required fields are present and not empty.
        
        :param data: Dictionary of input data
        :param required_fields: List of required field names
        :raises ValidationError: If any required field is missing or empty
        """
        missing_fields = []
        empty_fields = []
        
        for field in required_fields:
            if field not in data:
                missing_fields.append(field)
            elif data[field] in (None, '', [], {}):
                empty_fields.append(field)
        
        if missing_fields:
            raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
        
        if empty_fields:
            raise ValidationError(f"Empty required fields: {', '.join(empty_fields)}")
    
    @staticmethod
    def validate_integer(value, field_name, min_value=None, max_value=None):
        """
        Validate integer value with optional range.
        
        :param value: Value to validate
        :param field_name: Name of the field for error messages
        :param min_value: Minimum allowed value (optional)
        :param max_value: Maximum allowed value (optional)
        :raises ValidationError: If validation fails
        :return: Validated integer value
        """
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{field_name} must be an integer")
        
        if min_value is not None and int_value < min_value:
            raise ValidationError(f"{field_name} must be >= {min_value}")
        
        if max_value is not None and int_value > max_value:
            raise ValidationError(f"{field_name} must be <= {max_value}")
        
        return int_value
    
    @staticmethod
    def validate_float(value, field_name, min_value=None, max_value=None):
        """
        Validate float value with optional range.
        
        :param value: Value to validate
        :param field_name: Name of the field for error messages
        :param min_value: Minimum allowed value (optional)
        :param max_value: Maximum allowed value (optional)
        :raises ValidationError: If validation fails
        :return: Validated float value
        """
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{field_name} must be a number")
        
        if min_value is not None and float_value < min_value:
            raise ValidationError(f"{field_name} must be >= {min_value}")
        
        if max_value is not None and float_value > max_value:
            raise ValidationError(f"{field_name} must be <= {max_value}")
        
        return float_value
    
    @staticmethod
    def validate_string(value, field_name, min_length=None, max_length=None, pattern=None):
        """
        Validate string value with optional constraints.
        
        :param value: Value to validate
        :param field_name: Name of the field for error messages
        :param min_length: Minimum string length (optional)
        :param max_length: Maximum string length (optional)
        :param pattern: Regex pattern to match (optional)
        :raises ValidationError: If validation fails
        :return: Validated string value
        """
        if not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string")
        
        if min_length is not None and len(value) < min_length:
            raise ValidationError(f"{field_name} must be at least {min_length} characters")
        
        if max_length is not None and len(value) > max_length:
            raise ValidationError(f"{field_name} must be at most {max_length} characters")
        
        if pattern is not None and not re.match(pattern, value):
            raise ValidationError(f"{field_name} has invalid format")
        
        return value
    
    @staticmethod
    def validate_list(value, field_name, min_items=None, max_items=None):
        """
        Validate list with optional size constraints.
        
        :param value: Value to validate
        :param field_name: Name of the field for error messages
        :param min_items: Minimum number of items (optional)
        :param max_items: Maximum number of items (optional)
        :raises ValidationError: If validation fails
        :return: Validated list
        """
        if not isinstance(value, list):
            raise ValidationError(f"{field_name} must be a list")
        
        if min_items is not None and len(value) < min_items:
            raise ValidationError(f"{field_name} must have at least {min_items} items")
        
        if max_items is not None and len(value) > max_items:
            raise ValidationError(f"{field_name} must have at most {max_items} items")
        
        return value
    
    @staticmethod
    def validate_boolean(value, field_name):
        """
        Validate boolean value.
        
        :param value: Value to validate
        :param field_name: Name of the field for error messages
        :raises ValidationError: If validation fails
        :return: Validated boolean value
        """
        if not isinstance(value, bool):
            raise ValidationError(f"{field_name} must be a boolean")
        return value


class DataSanitizer:
    """Sanitizer for user input data."""
    
    @staticmethod
    def sanitize_string(value):
        """
        Sanitize string input to prevent XSS and injection attacks.
        
        :param value: String to sanitize
        :return: Sanitized string
        """
        if value is None:
            return None
        
        if not isinstance(value, str):
            value = str(value)
        
        # HTML escape to prevent XSS
        sanitized = html.escape(value)
        
        # Remove null bytes
        sanitized = sanitized.replace('\x00', '')
        
        return sanitized
    
    @staticmethod
    def sanitize_dict(data, allowed_keys=None):
        """
        Sanitize dictionary by removing unwanted keys and sanitizing values.
        
        :param data: Dictionary to sanitize
        :param allowed_keys: List of allowed keys (optional)
        :return: Sanitized dictionary
        """
        if not isinstance(data, dict):
            return {}
        
        sanitized = {}
        
        for key, value in data.items():
            # Skip keys not in allowed list if provided
            if allowed_keys is not None and key not in allowed_keys:
                _logger.warning(f"Skipping unauthorized key: {key}")
                continue
            
            # Sanitize based on value type
            if isinstance(value, str):
                sanitized[key] = DataSanitizer.sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[key] = DataSanitizer.sanitize_dict(value, allowed_keys)
            elif isinstance(value, list):
                sanitized[key] = [
                    DataSanitizer.sanitize_string(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        
        return sanitized
    
    @staticmethod
    def sanitize_sql_identifier(identifier):
        """
        Sanitize SQL identifier (table name, column name, etc.).
        
        :param identifier: Identifier to sanitize
        :return: Sanitized identifier
        :raises ValidationError: If identifier contains invalid characters
        """
        if not isinstance(identifier, str):
            raise ValidationError("SQL identifier must be a string")
        
        # Only allow alphanumeric and underscore
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
            raise ValidationError("Invalid SQL identifier format")
        
        return identifier


class PermissionChecker:
    """Permission checker for controller endpoints."""
    
    @staticmethod
    def check_user_authenticated(env):
        """
        Check if user is authenticated.
        
        :param env: Odoo environment
        :raises ValidationError: If user is not authenticated
        """
        if not env.user or env.user.id == env.ref('base.public_user').id:
            raise ValidationError("Authentication required")
    
    @staticmethod
    def check_user_has_group(env, group_xml_id):
        """
        Check if user belongs to a specific group.
        
        :param env: Odoo environment
        :param group_xml_id: XML ID of the group (e.g., 'base.group_user')
        :raises ValidationError: If user doesn't have the required group
        """
        PermissionChecker.check_user_authenticated(env)
        
        if not env.user.has_group(group_xml_id):
            raise ValidationError(f"Insufficient permissions. Required group: {group_xml_id}")
    
    @staticmethod
    def check_pos_session_access(env, session_id):
        """
        Check if user has access to a specific POS session.
        
        :param env: Odoo environment
        :param session_id: POS session ID
        :raises ValidationError: If user doesn't have access
        :return: POS session record
        """
        PermissionChecker.check_user_authenticated(env)
        
        session = env['pos.session'].sudo().browse(session_id)
        if not session.exists():
            raise ValidationError(f"POS session {session_id} not found")
        
        # Check if user has access (can be customized based on requirements)
        if not env.user.has_group('point_of_sale.group_pos_user'):
            raise ValidationError("POS user permission required")
        
        return session
    
    @staticmethod
    def check_restaurant_access(env, restaurant_id):
        """
        Check if user has access to a specific restaurant.
        
        :param env: Odoo environment
        :param restaurant_id: Restaurant ID
        :raises ValidationError: If user doesn't have access
        """
        PermissionChecker.check_user_authenticated(env)
        
        # Get restaurant_id from config
        config_restaurant_id = env['ir.config_parameter'].sudo().get_param('restaurant_id')
        
        if str(restaurant_id) != str(config_restaurant_id):
            raise ValidationError("Access denied to this restaurant")

