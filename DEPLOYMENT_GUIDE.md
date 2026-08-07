# Guía de Deployment - Sistema OCR NAD Scanner

## Requisitos Previos

### Sistema
- **OS:** Linux (Ubuntu 20.04+ recomendado), Windows, macOS
- **Python:** 3.11+
- **RAM:** 4GB mínimo (8GB recomendado)
- **Espacio:** 2GB mínimo

### Dependencias del Sistema
- **Tesseract OCR:** Para reconocimiento de texto
- **Poppler:** Para procesamiento de PDF
- **OpenCV:** Para procesamiento de imágenes

## Opciones de Deployment

### Opción 1: Instalación Local (Recomendada para Desarrollo)

#### Paso 1: Clonar el Repositorio
```bash
git clone <repository-url>
cd nadscanner_final
```

#### Paso 2: Ejecutar Script de Instalación
```bash
# Modo desarrollo
bash setup.sh dev

# Modo producción
bash setup.sh prod
```

#### Paso 3: Configurar Variables de Entorno
```bash
cp .env.example .env
# Editar .env con tus credenciales reales
nano .env
```

#### Paso 4: Ejecutar el Sistema
```bash
# Activar entorno virtual
source venv/bin/activate

# Ejecutar
python main.py
```

### Opción 2: Docker (Recomendada para Producción)

#### Paso 1: Construir Imagen Docker
```bash
docker build -t nadscanner-ocr:latest .
```

#### Paso 2: Ejecutar Contenedor
```bash
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  nadscanner-ocr:latest
```

#### Paso 3: Verificar Estado
```bash
docker ps
docker logs <container-id>
```

### Opción 3: Docker Compose (Recomendada para Producción con Base de Datos)

#### Paso 1: Crear docker-compose.yml
```yaml
version: '3.8'

services:
  ocr:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./output:/app/output
      - ./data:/app/data
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - ocr
    restart: unless-stopped
```

#### Paso 2: Ejecutar
```bash
docker-compose up -d
```

## Configuración de Producción

### Variables de Entorno Requeridas

```bash
# Supabase (Base de datos en la nube)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here

# Servidor
PORT=5000
HOST=0.0.0.0

# Logging
LOG_LEVEL=INFO
DEBUG=false
```

### Configuración de Directorios

```bash
/var/lib/nadscanner/output/  # Salida de procesamiento
/var/lib/nadscanner/data/    # Datos y caché
/var/log/nadscanner/         # Logs del sistema
```

### Configuración de Tesseract

**Linux:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-spa
```

**Windows:**
- Descargar desde: https://github.com/UB-Mannheim/tesseract/wiki
- Instalar en: `C:/Program Files/Tesseract-OCR/`

**macOS:**
```bash
brew install tesseract
brew install tesseract-lang
```

## Configuración de SSL/HTTPS (Opcional)

### Usando Nginx

#### Paso 1: Instalar Certbot
```bash
sudo apt-get install certbot python3-certbot-nginx
```

#### Paso 2: Obtener Certificado SSL
```bash
sudo certbot --nginx -d tu-dominio.com
```

#### Paso 3: Configurar Nginx
```nginx
server {
    listen 443 ssl;
    server_name tu-dominio.com;

    ssl_certificate /etc/letsencrypt/live/tu-dominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tu-dominio.com/privkey.pem;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Monitoreo y Logs

### Ver Logs en Tiempo Real
```bash
# Local
tail -f logs/ocr.log

# Docker
docker logs -f <container-id>
```

### Métricas del Sistema
- Dashboard disponible en: `data/metrics_dashboard.html`
- API de métricas: `/api/metrics`

## Backup y Restauración

### Backup de Datos
```bash
# Backup de output
tar -czf backup-$(date +%Y%m%d).tar.gz output/ data/

# Backup de base de datos Supabase
# Usar herramientas de Supabase
```

### Restauración
```bash
# Restaurar backup
tar -xzf backup-YYYYMMDD.tar.gz
```

## Escalado

### Horizontal Scaling (Docker Swarm)
```bash
docker swarm init
docker service create --replicas 3 --name nadscanner-ocr nadscanner-ocr:latest
```

### Vertical Scaling
- Aumentar RAM del servidor
- Usar GPU para PaddleOCR (si está disponible)

## Troubleshooting

### Error: Tesseract no encontrado
```bash
# Linux
sudo apt-get install tesseract-ocr tesseract-ocr-spa

# Windows
# Descargar e instalar desde https://github.com/UB-Mannheim/tesseract/wiki
```

### Error: Dependencias faltantes
```bash
pip install -r requirements.txt --upgrade
```

### Error: Permisos de directorios
```bash
chmod -R 755 output/ data/ logs/
```

### Error: Memoria insuficiente
```bash
# Aumentar swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

## Checklist de Deployment

- [ ] Python 3.11+ instalado
- [ ] Tesseract OCR instalado
- [ ] Dependencias Python instaladas
- [ ] Archivo .env configurado
- [ ] Directorios creados (output, data, logs)
- [ ] Tests pasando (python tests/test_full_integration.py)
- [ ] Firewall configurado (puerto 5000)
- [ ] SSL configurado (opcional pero recomendado)
- [ ] Backup automatizado configurado
- [ ] Monitoreo configurado
- [ ] Logs rotativos configurados

## Soporte

Para problemas de deployment:
1. Verificar logs: `logs/ocr.log`
2. Ejecutar tests: `python tests/test_full_integration.py`
3. Revisar documentación: `CLAUDE_DOCUMENTATION.md`

---

**Última actualización:** Agosto 5, 2026
**Versión:** 4.0
