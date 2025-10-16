"""Security utilities for masking sensitive data in logs."""


def mask_sensitive_data(data, sensitive_keys=None):
    """
    Masque les données sensibles dans un dictionnaire pour les logs.
    
    :param data: Dictionnaire contenant potentiellement des données sensibles
    :param sensitive_keys: Liste des clés à masquer (par défaut: clés secrètes courantes)
    :return: Copie du dictionnaire avec les valeurs sensibles masquées
    """
    if sensitive_keys is None:
        sensitive_keys = [
            'secret_key',
            'odoo_secret_key',
            'x-secret-key',
            'x-odoo-secret-key',
            'x-odoo-key',
            'x-api-key',
            'password',
            'api_key',
            'access_token',
            'token',
            'authorization',
        ]
    
    if not isinstance(data, dict):
        return data
    
    masked_data = data.copy()
    
    for key in masked_data:
        # Masquer si la clé correspond à une clé sensible (insensible à la casse)
        if key.lower() in [k.lower() for k in sensitive_keys]:
            masked_data[key] = '***MASKED***'
        # Récursion pour les dictionnaires imbriqués
        elif isinstance(masked_data[key], dict):
            masked_data[key] = mask_sensitive_data(masked_data[key], sensitive_keys)
    
    return masked_data


def mask_headers(headers):
    """
    Masque les en-têtes HTTP sensibles pour les logs.
    
    :param headers: Dictionnaire d'en-têtes HTTP
    :return: Dictionnaire avec les valeurs sensibles masquées
    """
    return mask_sensitive_data(headers)

