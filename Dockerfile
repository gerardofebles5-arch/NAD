# ============================================================
# Dockerfile para Sistema OCR NAD Scanner (EasyOCR - Python puro)
# ============================================================
# Build: docker build -t nadscanner-ocr:latest .
# Run: docker run -p 5000:5000 nadscanner-ocr:latest
#
# EasyOCR no requiere binarios del sistema, funciona en plataformas gratuitas

FROM python:3.11-slim

# Configurar directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema mínimas (solo para PDF)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY . .

# Crear directorios necesarios
RUN mkdir -p output/queue output/render output/data data config logs

# Configurar variables de entorno
ENV PYTHONUNBUFFERED=1

# Exponer puerto
EXPOSE 5000

# Comando de inicio
CMD ["python", "web_server.py"]
