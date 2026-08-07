# ============================================================
# Dockerfile para Sistema OCR NAD Scanner
# ============================================================
# Build: docker build -t nadscanner-ocr:latest .
# Run: docker run -p 5000:5000 nadscanner-ocr:latest

FROM python:3.11-slim

# Configurar directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
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
ENV TESSERACT_CMD=/usr/bin/tesseract

# Exponer puerto
EXPOSE 5000

# Comando de inicio
CMD ["python", "main.py"]
