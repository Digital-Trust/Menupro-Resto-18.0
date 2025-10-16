"""Configuration cache utilities for MenuPro."""
import logging
from functools import lru_cache
from odoo import tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_menupro_config(env_registry_db_name):
    """
    Récupère et met en cache la configuration MenuPro.
    
    Le cache est basé sur le nom de la base de données pour éviter les conflits
    entre différentes bases de données dans un environnement multi-tenant.
    
    :param env_registry_db_name: Nom de la base de données (env.registry.db_name)
    :return: Dictionnaire de configuration
    """
    # Note: Cette fonction ne peut pas accéder directement à env car elle est cachée
    # Le cache est invalidé automatiquement quand Python redémarre
    return None  # Placeholder - sera rempli par la vraie fonction


class ConfigCache:
    """Gestionnaire de cache pour la configuration MenuPro."""
    
    _cache = {}
    _cache_timeout = 300  # 5 minutes en secondes
    
    @classmethod
    def get_config(cls, env, config_keys):
        """
        Récupère la configuration avec cache.
        
        :param env: Environment Odoo
        :param config_keys: Liste des clés de configuration à récupérer
        :return: Dictionnaire de configuration
        """
        import time
        
        cache_key = f"{env.registry.db_name}_{hash(tuple(sorted(config_keys)))}"
        current_time = time.time()
        
        # Vérifier si la config est en cache et toujours valide
        if cache_key in cls._cache:
            cached_data, cache_time = cls._cache[cache_key]
            if current_time - cache_time < cls._cache_timeout:
                _logger.debug("Configuration loaded from cache")
                return cached_data
        
        # Charger la configuration
        _logger.debug("Loading configuration from database and config file")
        ICParam = env['ir.config_parameter'].sudo()
        
        cfg = {}
        for key in config_keys:
            # Essayer d'abord dans tools.config
            value = tools.config.get(key)
            if not value and key == 'restaurant_id':
                # Pour restaurant_id, essayer dans ir.config_parameter
                value = ICParam.get_param('restaurant_id')
            cfg[key] = value
        
        # Valider que toutes les clés ont une valeur
        for k, v in cfg.items():
            if not v:
                _logger.error("%s is missing in config", k)
                raise UserError(f"L'option '{k}' est manquante dans la configuration.")
        
        # Stocker en cache
        cls._cache[cache_key] = (cfg, current_time)
        
        return cfg
    
    @classmethod
    def clear_cache(cls, env=None):
        """
        Vide le cache de configuration.
        
        :param env: Si fourni, ne vide que le cache pour cette base de données
        """
        if env:
            # Supprimer uniquement les entrées pour cette base de données
            db_name = env.registry.db_name
            keys_to_delete = [k for k in cls._cache.keys() if k.startswith(f"{db_name}_")]
            for key in keys_to_delete:
                del cls._cache[key]
            _logger.info("Cache cleared for database: %s", db_name)
        else:
            # Vider tout le cache
            cls._cache.clear()
            _logger.info("All configuration cache cleared")
    
    @classmethod
    def set_timeout(cls, timeout_seconds):
        """
        Définit le délai d'expiration du cache.
        
        :param timeout_seconds: Durée en secondes
        """
        cls._cache_timeout = timeout_seconds
        _logger.info("Cache timeout set to %s seconds", timeout_seconds)

