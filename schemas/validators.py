"""
πNAD - Pydantic Schemas for Validation
=====================================
Schemas para validar datos de entrada en los endpoints.
"""

from pydantic import BaseModel, Field, validator, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ═══════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════

class NotificationType(str, Enum):
    """Tipos de notificación."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class SyncOperation(str, Enum):
    """Tipos de operaciones de sincronización."""
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class PreviewMode(str, Enum):
    """Modos de preview."""
    EDGES = "edges"
    ALIGNMENT = "alignment"
    ENHANCEMENT = "enhancement"
    QUALITY = "quality"
    FULL = "full"


# ═══════════════════════════════════════════════════
#  Authentication Schemas
# ═══════════════════════════════════════════════════

class TokenValidationRequest(BaseModel):
    """Request para validar token JWT."""
    token: str = Field(..., min_length=1, description="Token JWT de Supabase")


class TokenValidationResponse(BaseModel):
    """Response de validación de token."""
    valid: bool
    user: Optional[Dict[str, Any]] = None
    tenant_id: Optional[int] = None
    error: Optional[str] = None


# ═══════════════════════════════════════════════════
#  Notification Schemas
# ═══════════════════════════════════════════════════

class CreateNotificationRequest(BaseModel):
    """Request para crear notificación."""
    user_id: str = Field(..., min_length=1, description="ID del usuario")
    title: str = Field(..., min_length=1, max_length=200, description="Título de la notificación")
    body: str = Field(..., min_length=1, max_length=1000, description="Cuerpo de la notificación")
    icon: str = Field(default="", max_length=100, description="URL del icono")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Datos adicionales")
    type: NotificationType = Field(default=NotificationType.INFO, description="Tipo de notificación")


class NotificationResponse(BaseModel):
    """Response de notificación."""
    id: Optional[int]
    user_id: str
    title: str
    body: str
    icon: str
    data: Dict[str, Any]
    created_at: str
    read: bool
    type: str


class MarkAllReadRequest(BaseModel):
    """Request para marcar todas como leídas."""
    user_id: str = Field(..., min_length=1, description="ID del usuario")


# ═══════════════════════════════════════════════════
#  Sync Schemas
# ═══════════════════════════════════════════════════

class SyncPushRequest(BaseModel):
    """Request para sincronización push."""
    table: Optional[str] = Field(None, description="Nombre de la tabla")
    limit: int = Field(default=50, ge=1, le=100, description="Máximo de registros")


class SyncPullRequest(BaseModel):
    """Request para sincronización pull."""
    table: Optional[str] = Field(None, description="Nombre de la tabla")
    since: Optional[str] = Field(None, description="Fecha ISO desde la cual buscar cambios")


class SyncConflictResolutionRequest(BaseModel):
    """Request para resolver conflicto de sincronización."""
    operation_id: int = Field(..., ge=1, description="ID de la operación")
    resolution: str = Field(..., description="Estrategia de resolución")
    merged_data: Optional[Dict[str, Any]] = Field(None, description="Datos fusionados (si merge)")


# ═══════════════════════════════════════════════════
#  Formula Recognition Schemas
# ═══════════════════════════════════════════════════

class FormulaResult(BaseModel):
    """Resultado de reconocimiento de fórmula."""
    latex: str
    confidence: float = Field(..., ge=0, le=1, description="Confianza del reconocimiento")
    bbox: List[int] = Field(..., min_length=4, max_length=4, description="Coordenadas [x1, y1, x2, y2]")


class FormulaRecognitionResponse(BaseModel):
    """Response de reconocimiento de fórmulas."""
    success: bool
    formulas: List[FormulaResult]
    count: int
    error: Optional[str] = None


# ═══════════════════════════════════════════════════
#  WebSocket Schemas
# ═══════════════════════════════════════════════════

class PreviewFrameRequest(BaseModel):
    """Request para procesar frame de preview."""
    image: str = Field(..., min_length=1, description="Imagen en base64")
    mode: PreviewMode = Field(default=PreviewMode.FULL, description="Modo de preview")


class PreviewFrameResponse(BaseModel):
    """Response de procesamiento de frame."""
    processed_image: str
    stats: Dict[str, Any]
    mode: str


class SetPreviewModeRequest(BaseModel):
    """Request para cambiar modo de preview."""
    mode: PreviewMode = Field(..., description="Nuevo modo de preview")


class SetPreviewModeResponse(BaseModel):
    """Response de cambio de modo."""
    mode: str
    message: str


# ═══════════════════════════════════════════════════
#  Tenant Schemas
# ═══════════════════════════════════════════════════

class CreateTenantRequest(BaseModel):
    """Request para crear tenant."""
    name: str = Field(..., min_length=1, max_length=200, description="Nombre de la empresa")
    email: Optional[EmailStr] = Field(None, description="Email de contacto")
    phone: Optional[str] = Field(None, max_length=50, description="Teléfono")
    address: Optional[str] = Field(None, max_length=500, description="Dirección")
    rif: Optional[str] = Field(None, max_length=50, description="RIF")
    max_users: int = Field(default=10, ge=1, le=1000, description="Máximo de usuarios")
    max_storage_mb: int = Field(default=500, ge=100, le=100000, description="Máximo de almacenamiento en MB")
    notes: Optional[str] = Field(None, max_length=1000, description="Notas")


class UpdateTenantRequest(BaseModel):
    """Request para actualizar tenant."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    rif: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None
    max_users: Optional[int] = Field(None, ge=1, le=1000)
    max_storage_mb: Optional[int] = Field(None, ge=100, le=100000)
    notes: Optional[str] = Field(None, max_length=1000)


class AddTenantUserRequest(BaseModel):
    """Request para agregar usuario a tenant."""
    tenant_id: int = Field(..., ge=1, description="ID del tenant")
    user_email: EmailStr = Field(..., description="Email del usuario")
    user_name: Optional[str] = Field(None, max_length=200, description="Nombre del usuario")
    role: str = Field(default="user", description="Rol del usuario")


# ═══════════════════════════════════════════════════
#  Invoice Schemas
# ═══════════════════════════════════════════════════

class InvoiceData(BaseModel):
    """Datos de factura extraídos."""
    invoice_number: Optional[str] = Field(None, max_length=100)
    date: Optional[str] = Field(None, description="Fecha en formato ISO")
    total: Optional[float] = Field(None, ge=0)
    subtotal: Optional[float] = Field(None, ge=0)
    tax: Optional[float] = Field(None, ge=0)
    vendor: Optional[str] = Field(None, max_length=200)
    items: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    
    @validator('total', 'subtotal', 'tax')
    def validate_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError('El valor no puede ser negativo')
        return v


class AssignInvoiceRequest(BaseModel):
    """Request para asignar factura a tenant."""
    invoice_id: int = Field(..., ge=1, description="ID de la factura")
    tenant_id: int = Field(..., ge=1, description="ID del tenant")


# ═══════════════════════════════════════════════════
#  Generic Response Schemas
# ═══════════════════════════════════════════════════

class SuccessResponse(BaseModel):
    """Response genérico de éxito."""
    success: bool = True
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    """Response genérico de error."""
    success: bool = False
    error: str
    message: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Response paginado."""
    success: bool
    data: List[Any]
    total: int
    page: int
    per_page: int
    total_pages: int
