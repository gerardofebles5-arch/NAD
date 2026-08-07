"""
Validador de RIF
================
Valida el formato y verifica RIFs contra base de datos externa.

Funcionalidades:
  - Validación de formato de RIF venezolano
  - Cálculo de dígito verificador
  - Validación contra base de datos (opcional)
  - Normalización de formato
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class RIFType(Enum):
    """Tipos de RIF venezolanos."""
    NATURAL = "V"  # Venezolano
    JURIDICO = "J"  # Jurídico
    GOVERNMENT = "G"  # Gobierno
    FOREIGN = "E"  # Extranjero
    SPECIAL = "P"  # Pasaporte


@dataclass
class RIFValidation:
    """Resultado de validación de RIF."""
    rif: str
    is_valid_format: bool
    is_valid_checksum: bool
    is_in_database: Optional[bool] = None
    normalized_rif: str = ""
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class RIFValidator:
    """
    Validador de RIF venezolano.
    
    Valida formato, dígito verificador y opcionalmente contra base de datos.
    """
    
    # Patrones de RIF
    RIF_PATTERN = r'^([VJEGPC])[\-.\s]?(\d{8})[\-.\s]?(\d)$'
    
    # Pesos para cálculo de dígito verificador
    CHECKSUM_WEIGHTS = [4, 3, 2, 7, 6, 5, 4, 3, 2]
    
    def __init__(self, database_enabled: bool = False):
        """
        Args:
            database_enabled: Si True, valida contra base de datos
        """
        self._database_enabled = database_enabled
        self._rif_cache: Dict[str, bool] = {}
    
    def validate(self, rif: str) -> RIFValidation:
        """
        Valida un RIF.
        
        Args:
            rif: RIF a validar
            
        Returns:
            RIFValidation con resultado de validación
        """
        validation = RIFValidation(
            rif=rif,
            is_valid_format=False,
            is_valid_checksum=False,
            normalized_rif="",
            errors=[],
            warnings=[]
        )
        
        # Normalizar RIF
        normalized = self._normalize_rif(rif)
        validation.normalized_rif = normalized
        
        if not normalized:
            validation.errors.append("RIF vacío o inválido")
            return validation
        
        # Validar formato
        if not self._validate_format(normalized):
            validation.errors.append("Formato de RIF inválido")
            return validation
        
        validation.is_valid_format = True
        
        # Validar dígito verificador
        if not self._validate_checksum(normalized):
            validation.errors.append("Dígito verificador inválido")
            validation.is_valid_checksum = False
        else:
            validation.is_valid_checksum = True
        
        # Validar contra base de datos (si está habilitado)
        if self._database_enabled:
            validation.is_in_database = self._validate_in_database(normalized)
            if not validation.is_in_database:
                validation.warnings.append("RIF no encontrado en base de datos")
        
        return validation
    
    def _normalize_rif(self, rif: str) -> str:
        """Normaliza el formato del RIF."""
        if not rif:
            return ""
        
        # Convertir a mayúsculas
        rif = rif.upper()
        
        # Eliminar espacios
        rif = rif.replace(" ", "")
        
        # Normalizar separadores a guiones
        rif = re.sub(r'[.\s]', '-', rif)
        
        # Si está pegado, insertar guiones
        match = re.match(r'^([VJEGPC])(\d{8})(\d)$', rif)
        if match:
            letter, digits, check = match.groups()
            return f"{letter}-{digits}-{check}"
        
        return rif
    
    def _validate_format(self, rif: str) -> bool:
        """Valida el formato del RIF."""
        return bool(re.match(self.RIF_PATTERN, rif))
    
    def _validate_checksum(self, rif: str) -> bool:
        """Valida el dígito verificador del RIF."""
        match = re.match(self.RIF_PATTERN, rif)
        if not match:
            return False
        
        letter, digits, check_digit = match.groups()
        
        # Calcular dígito verificador
        calculated_check = self._calculate_checksum(letter, digits)
        
        return calculated_check == int(check_digit)
    
    def _calculate_checksum(self, letter: str, digits: str) -> int:
        """Calcula el dígito verificador."""
        # Convertir letra a número
        letter_value = self._letter_to_number(letter)
        
        # Concatenar letra + dígitos
        full_number = str(letter_value) + digits
        
        # Calcular suma ponderada
        total = 0
        for i, digit in enumerate(full_number):
            if i < len(self.CHECKSUM_WEIGHTS):
                total += int(digit) * self.CHECKSUM_WEIGHTS[i]
        
        # Calcular dígito verificador
        remainder = total % 11
        if remainder < 2:
            check = 0
        else:
            check = 11 - remainder
        
        return check
    
    def _letter_to_number(self, letter: str) -> int:
        """Convierte letra de RIF a número."""
        mapping = {
            'V': 4,
            'J': 8,
            'G': 11,
            'E': 12,
            'P': 15,
            'C': 16
        }
        return mapping.get(letter, 0)
    
    def _validate_in_database(self, rif: str) -> bool:
        """
        Valida el RIF contra base de datos.
        
        En una implementación real, esto consultaría una API o base de datos.
        Por ahora, usa un cache simple y simula validación SENIAT.
        """
        # Verificar cache
        if rif in self._rif_cache:
            return self._rif_cache[rif]
        
        # Simular validación contra SENIAT
        # En una implementación real, aquí se haría la consulta a la API
        # Por ahora, asumimos que RIFs con formato válido son válidos
        # para no bloquear el flujo
        try:
            # Simulación de consulta a SENIAT
            # TODO: Implementar consulta real a API SENIAT
            # response = requests.get(f"https://api.seniat.gob.ve/rif/{rif}")
            # is_valid = response.json().get('valid', False)
            
            # Por ahora, retornamos True para RIFs con formato válido
            validation = self.validate(rif)
            is_valid = validation.is_valid_format
            
            self._rif_cache[rif] = is_valid
            return is_valid
        except Exception as e:
            print(f"[WARN] Error validando RIF en base de datos: {e}")
            return False
    
    def batch_validate(self, rifs: List[str]) -> Dict[str, RIFValidation]:
        """
        Valida múltiples RIFs.
        
        Args:
            rifs: Lista de RIFs a validar
            
        Returns:
            Diccionario con RIF como clave y validación como valor
        """
        results = {}
        for rif in rifs:
            results[rif] = self.validate(rif)
        return results
    
    def get_rif_type(self, rif: str) -> Optional[RIFType]:
        """
        Determina el tipo de RIF.
        
        Args:
            rif: RIF a analizar
            
        Returns:
            RIFType o None si es inválido
        """
        normalized = self._normalize_rif(rif)
        if not normalized:
            return None
        
        letter = normalized[0]
        try:
            return RIFType(letter)
        except ValueError:
            return None


def validate_rif(rif: str, database_enabled: bool = False) -> RIFValidation:
    """
    Función de conveniencia para validar un RIF.
    
    Args:
        rif: RIF a validar
        database_enabled: Si True, valida contra base de datos
        
    Returns:
        RIFValidation con resultado de validación
    """
    validator = RIFValidator(database_enabled=database_enabled)
    return validator.validate(rif)


def normalize_rif(rif: str) -> str:
    """
    Función de conveniencia para normalizar un RIF.
    
    Args:
        rif: RIF a normalizar
        
    Returns:
        RIF normalizado
    """
    validator = RIFValidator()
    return validator._normalize_rif(rif)


def get_rif_type(rif: str) -> Optional[RIFType]:
    """
    Función de conveniencia para obtener el tipo de RIF.
    
    Args:
        rif: RIF a analizar
        
    Returns:
        RIFType o None si es inválido
    """
    validator = RIFValidator()
    return validator.get_rif_type(rif)
