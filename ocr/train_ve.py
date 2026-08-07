"""
πNAD — Synthetic Data Generator & Fine-Tuning Pipeline para PaddleOCR VE
========================================================================
Genera datasets sintéticos de facturas venezolanas con ground truth
para fine-tuning de PaddleOCR en reconocimiento de documentos VE.

Pipelines:
  1. generate_dataset() — Crea imágenes sintéticas de facturas VE
  2. prepare_ppocr_format() — Convierte a formato PPOCR (label.txt)
  3. run_finetune() — Ejecuta fine-tuning con PaddleOCR tools

Uso:
    python -m ocr.train_ve generate --count 200
    python -m ocr.train_ve prepare --input ./synthetic_data --output ./ppocr_dataset
    python -m ocr.train_ve finetune --dataset ./ppocr_dataset
"""

import os
import re
import csv
import json
import math
import random
import argparse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np


# ──────────────────────────────────────────────
#  Generador de datos sintéticos
# ──────────────────────────────────────────────

@dataclass
class VEFacturaTemplate:
    """Plantilla de factura venezolana con valores aleatorios."""
    rif_emisor: str = "J-12345678-9"
    razon_social: str = "COMERCIALIZADORA EJEMPLO C.A."
    direccion: str = "Av. Principal, Edif. Centro, Piso 3, Caracas"
    telefono: str = "0212-5551234"
    numero_factura: str = "001-00012345"
    numero_control: str = "01-12345678"
    fecha: str = "15/01/2025"
    condicion_pago: str = "CONTADO"
    cliente: str = "CLIENTE GENÉRICO S.A."
    cliente_rif: str = "J-87654321-0"
    items: List[Dict] = field(default_factory=list)
    base_imponible: float = 0.0
    iva: float = 0.0
    iva_rate: float = 16.0
    total: float = 0.0


class VEFacturaGenerator:
    """
    Generador de facturas venezolanas sintéticas.

    Crea imágenes renderizadas con PIL/Pillow más archivos de
    anotación en formato PaddleOCR (label.txt con coordenadas).
    """

    # Letras RIF
    RIF_LETTERS = ['J', 'V', 'E', 'P', 'G']

    # Nombres de empresas Ve
    EMPRESAS = [
        "COMERCIALIZADORA NACIONAL C.A.",
        "SERVICIOS INTEGRALES R&R S.A.",
        "DISTRIBUIDORA VENEZOLANA C.A.",
        "EMPRESA DE SERVICIOS MÚLTIPLES S.A.",
        "CONSTRUCTORA ORIENTAL C.A.",
        "INVERSIONES CARIBE S.A.",
        "PRODUCTOS ALIMENTICIOS C.A.",
        "TECNOLOGÍA AVANZADA S.A.",
        "TRANSPORTES RÁPIDOS C.A.",
        "SUMINISTROS INDUSTRIALES S.A.",
        "SOLUCIONES EMPRESARIALES C.A.",
        "COMERCIAL LA FUENTE S.A.",
        "SERVICIOS TURÍSTICOS C.A.",
        "AGENCIA ADUANERA NACIONAL S.A.",
        "LABORATORIOS FARMACÉUTICOS C.A.",
    ]

    # Productos VE comunes
    PRODUCTOS = [
        ("Producto de Limpieza X", 12.50),
        ("Artículo de Oficina", 25.00),
        ("Material Promocional", 45.00),
        ("Servicio de Consultoría", 150.00),
        ("Mantenimiento Preventivo", 80.00),
        ("Equipo de Computación", 350.00),
        ("Suministros Varios", 30.00),
        ("Servicio de Instalación", 200.00),
        ("Repuestos Industriales", 95.00),
        ("Material Publicitario", 60.00),
        ("Software de Gestión", 500.00),
        ("Asesoría Legal", 250.00),
        ("Servicio de Mensajería", 15.00),
        ("Insumos Médicos", 180.00),
        ("Mobiliario de Oficina", 420.00),
    ]

    # Ciudades VE
    CIUDADES = ["Caracas", "Maracaibo", "Valencia", "Barquisimeto", "Maracay"]

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._counter = 0

    def generate_random_rif(self) -> str:
        """Genera un RIF venezolano aleatorio."""
        letter = self.rng.choice(self.RIF_LETTERS)
        digits = ''.join(str(self.rng.randint(0, 9)) for _ in range(8))
        check = str(self.rng.randint(0, 9))
        return f"{letter}-{digits}-{check}"

    def generate_random_factura(self) -> VEFacturaTemplate:
        """Genera una factura venezolana aleatoria."""
        fact = VEFacturaTemplate()

        # Datos del emisor
        fact.rif_emisor = self.generate_random_rif()
        fact.razon_social = self.rng.choice(self.EMPRESAS)
        fact.direccion = (
            f"{self.rng.choice(['Av.', 'Calle', 'Urb.', 'Sector'])} "
            f"{self.rng.choice(['Principal', 'Bolívar', 'Libertador', 'Las Flores', 'El Cafetal'])}, "
            f"Edif. {self.rng.choice(['Centro', 'Empresarial', 'Comercial', 'Ejecutivo'])}, "
            f"Piso {self.rng.randint(1, 10)}, {self.rng.choice(self.CIUDADES)}"
        )
        fact.telefono = f"0{self.rng.choice([212, 241, 261, 251, 243])}-{self.rng.randint(1000000, 9999999)}"

        # Datos del documento
        fact.numero_factura = f"{self.rng.randint(1, 999):03d}-{self.rng.randint(10000, 99999):05d}"
        fact.numero_control = f"{self.rng.randint(1, 99):02d}-{self.rng.randint(10000000, 99999999)}"
        fact.fecha = datetime.now() - timedelta(days=self.rng.randint(1, 365))
        fact.fecha = fact.fecha.strftime("%d/%m/%Y")
        fact.condicion_pago = self.rng.choice(["CONTADO", "CRÉDITO 30 DÍAS", "CRÉDITO 60 DÍAS", "CHEQUE"])

        # Cliente
        fact.cliente = self.rng.choice(self.EMPRESAS)
        fact.cliente_rif = self.generate_random_rif()

        # Items
        num_items = self.rng.randint(1, 6)
        items = []
        subtotal = 0.0
        for _ in range(num_items):
            prod_name, base_price = self.rng.choice(self.PRODUCTOS)
            qty = self.rng.randint(1, 50)
            unit_price = round(base_price * self.rng.uniform(0.8, 1.2), 2)
            total_price = round(qty * unit_price, 2)
            items.append({
                "cantidad": qty,
                "descripcion": prod_name,
                "precio_unitario": unit_price,
                "total": total_price,
            })
            subtotal += total_price

        fact.items = items
        fact.base_imponible = round(subtotal, 2)
        fact.iva_rate = self.rng.choice([16.0, 8.0, 16.0])  # 16% predominante
        fact.iva = round(fact.base_imponible * fact.iva_rate / 100, 2)
        fact.total = round(fact.base_imponible + fact.iva, 2)

        self._counter += 1
        return fact

    def factura_to_text_lines(self, fact: VEFacturaTemplate) -> List[str]:
        """
        Convierte una factura a líneas de texto formateado.
        Útil para generar imágenes renderizadas posteriormente.
        """
        lines = []
        lines.append(f"  {fact.razon_social}")
        lines.append(f"  RIF: {fact.rif_emisor}")
        lines.append(f"  {fact.direccion}")
        lines.append(f"  TELÉFONO: {fact.telefono}")
        lines.append("")
        lines.append(f"  FACTURA N°: {fact.numero_factura}          CONTROL N°: {fact.numero_control}")
        lines.append(f"  FECHA: {fact.fecha}")
        lines.append(f"  CONDICIÓN DE PAGO: {fact.condicion_pago}")
        lines.append("")
        lines.append(f"  CLIENTE: {fact.cliente}")
        lines.append(f"  RIF: {fact.cliente_rif}")
        lines.append("")
        lines.append("  ─────────────────────────────────────────────")
        lines.append("  CANT.  DESCRIPCIÓN        P. UNIT.     TOTAL")
        lines.append("  ─────────────────────────────────────────────")
        for item in fact.items:
            qty_str = f"{item['cantidad']:5d}"
            desc_str = f"{item['descripcion']:20s}"
            price_str = f"Bs. {item['precio_unitario']:>8.2f}"
            total_str = f"Bs. {item['total']:>8.2f}"
            lines.append(f"  {qty_str}  {desc_str}  {price_str}  {total_str}")
        lines.append("  ─────────────────────────────────────────────")
        lines.append("")
        lines.append(f"  BASE IMPONIBLE:     Bs. {fact.base_imponible:>10.2f}")
        lines.append(f"  IVA ({fact.iva_rate:.0f}%):            Bs. {fact.iva:>10.2f}")
        lines.append(f"  TOTAL:              Bs. {fact.total:>10.2f}")
        lines.append("")
        lines.append(f"  SON: {num_to_words_ve(fact.total)} BOLÍVARES")
        lines.append("")
        lines.append("  ─────────────────────────────────────────────")
        lines.append("  FIRMA AUTORIZADA                  SELLO")
        return lines

    def generate_ground_truth(self, fact: VEFacturaTemplate) -> Dict:
        """Genera el ground truth completo (todos los campos)."""
        return {
            "filename": f"factura_{self._counter:04d}.png",
            "rif_emisor": fact.rif_emisor,
            "razon_social": fact.razon_social,
            "direccion": fact.direccion,
            "telefono": fact.telefono,
            "numero_factura": fact.numero_factura,
            "numero_control": fact.numero_control,
            "fecha": fact.fecha,
            "condicion_pago": fact.condicion_pago,
            "cliente": fact.cliente,
            "cliente_rif": fact.cliente_rif,
            "base_imponible": fact.base_imponible,
            "iva": fact.iva,
            "iva_rate": fact.iva_rate,
            "total": fact.total,
            "items": fact.items,
            "full_text": "\n".join(self.factura_to_text_lines(fact)),
        }


def num_to_words_ve(n: float) -> str:
    """Convierte un número a palabras en español venezolano."""
    # Implementación simplificada
    units = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS",
             "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE"]
    tens = ["", "", "VEINTI", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA",
            "SETENTA", "OCHENTA", "NOVENTA"]
    
    integer_part = int(n)
    decimal_part = int(round((n - integer_part) * 100))
    
    def convert_group(num):
        if num == 0:
            return ""
        if num < 21:
            return units[num]
        if num < 100:
            t = num // 10
            u = num % 10
            if u == 0:
                return tens[t]
            if t == 2:
                return f"VEINTI{units[u].lower()}"
            return f"{tens[t]} Y {units[u].lower()}"
        if num < 1000:
            c = num // 100
            rest = num % 100
            prefix = "CIENTO" if c > 1 else "CIEN"
            if c > 1:
                # Excepciones: 500=QUINIENTOS, 700=SETECIENTOS
                excepciones = {5: "QUINIENTOS", 7: "SETECIENTOS", 9: "NOVECIENTOS"}
                prefix = excepciones.get(c, units[c] + "CIENTOS")
            if rest == 0:
                return prefix
            return f"{prefix} {convert_group(rest).lower()}"
        return str(num)
    
    if integer_part == 0:
        words = "CERO"
    elif integer_part == 1:
        words = "UN"
    elif integer_part < 1000000:
        thousands = integer_part // 1000
        rest = integer_part % 1000
        words = ""
        if thousands > 0:
            if thousands == 1:
                words = "MIL"
            else:
                words = convert_group(thousands) + " MIL"
        if rest > 0:
            if words:
                words += " "
            words += convert_group(rest).lower()
    else:
        words = str(integer_part)
    
    return f"{words} CON {decimal_part:02d}/100"


# ──────────────────────────────────────────────
#  Generación de dataset renderizado
# ──────────────────────────────────────────────

def generate_dataset(
    output_dir: str = "./synthetic_data",
    count: int = 100,
    seed: int = 42,
    with_images: bool = True,
):
    """
    Genera un dataset sintético de facturas venezolanas.

    Args:
        output_dir: Directorio de salida.
        count: Número de facturas a generar.
        seed: Semilla aleatoria.
        with_images: Si True, genera imágenes renderizadas (requiere PIL).
    """
    os.makedirs(output_dir, exist_ok=True)

    generator = VEFacturaGenerator(seed=seed)
    labels = []
    gt_file = os.path.join(output_dir, "ground_truth.json")

    print(f"📄 Generando {count} facturas sintéticas...")

    for i in range(count):
        fact = generator.generate_random_factura()
        gt = generator.generate_ground_truth(fact)
        gt["id"] = i

        # Guardar ground truth como JSON
        gt_path = os.path.join(output_dir, f"factura_{i:04d}.json")
        with open(gt_path, 'w', encoding='utf-8') as f:
            json.dump(gt, f, indent=2, ensure_ascii=False)

        labels.append({
            "filename": f"factura_{i:04d}.png",
            "text": gt["full_text"],
        })

        if (i + 1) % 10 == 0:
            print(f"  → {i + 1}/{count} generadas...")

    # Guardar ground truth agregado
    with open(gt_file, 'w', encoding='utf-8') as f:
        json.dump({
            "count": count,
            "seed": seed,
            "generated_at": datetime.now().isoformat(),
            "fields": list(labels[0].keys()) if labels else [],
        }, f, indent=2, ensure_ascii=False)

    # Guardar label.txt para PPOCR
    label_path = os.path.join(output_dir, "label.txt")
    with open(label_path, 'w', encoding='utf-8') as f:
        for label in labels:
            f.write(f"{label['filename']}\t{label['text']}\n")

    print(f"\n✅ Dataset generado en: {output_dir}")
    print(f"   • {count} facturas sintéticas")
    print(f"   • ground_truth.json")
    print(f"   • label.txt")

    # Si se pide con imágenes, generarlas con PIL
    if with_images:
        try:
            from PIL import Image, ImageDraw, ImageFont
            _render_images(generator, labels, output_dir)
        except ImportError:
            print("   ⚠ PIL no disponible. Las imágenes no se generaron.")
            print("     Instale: pip install Pillow")

    return output_dir


def _render_images(
    generator: VEFacturaGenerator,
    labels: List[Dict],
    output_dir: str,
):
    """Renderiza imágenes de facturas sintéticas con PIL."""
    from PIL import Image, ImageDraw, ImageFont

    # Intentar cargar una fuente monoespaciada
    font = None
    for font_name in ["Courier New", "DejaVu Sans Mono", "Liberation Mono", "Consolas", "FreeMono"]:
        try:
            font = ImageFont.truetype(font_name, 14)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    print(f"\n🎨 Renderizando {len(labels)} imágenes...")

    for i, label in enumerate(labels):
        text = label["text"]
        lines = text.split('\n')
        
        # Calcular dimensiones
        line_height = 20
        padding = 20
        max_chars = max(len(l) for l in lines) if lines else 80
        char_width = 9
        
        width = max_chars * char_width + padding * 2
        height = len(lines) * line_height + padding * 2

        # Crear lienzo
        img = Image.new('RGB', (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Dibujar texto
        y = padding
        for line in lines:
            draw.text((padding, y), line, fill=(0, 0, 0), font=font)
            y += line_height

        # Guardar
        img_path = os.path.join(output_dir, label["filename"])
        img.save(img_path, 'PNG')

        if (i + 1) % 20 == 0:
            print(f"  → {i + 1}/{len(labels)} imágenes renderizadas...")

    print(f"  ✅ {len(labels)} imágenes renderizadas")


# ──────────────────────────────────────────────
#  Conversión a formato PPOCR
# ──────────────────────────────────────────────

def prepare_ppocr_format(
    input_dir: str = "./synthetic_data",
    output_dir: str = "./ppocr_dataset",
    split_ratio: float = 0.8,
):
    """
    Convierte dataset sintético a formato PaddleOCR (PPOCR).

    Args:
        input_dir: Directorio con datos sintéticos.
        output_dir: Directorio de salida PPOCR.
        split_ratio: Proporción train/test.
    """
    from shutil import copy2

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "train"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "test"), exist_ok=True)

    # Leer ground truth
    gt_path = os.path.join(input_dir, "ground_truth.json")
    if os.path.exists(gt_path):
        with open(gt_path, 'r', encoding='utf-8') as f:
            gt_meta = json.load(f)
        count = gt_meta.get("count", 0)
    else:
        count = len([f for f in os.listdir(input_dir) if f.endswith('.json') and f != 'ground_truth.json'])

    # Obtener lista de archivos y mezclar
    files = []
    for i in range(count):
        img_path = os.path.join(input_dir, f"factura_{i:04d}.png")
        gt_path = os.path.join(input_dir, f"factura_{i:04d}.json")
        if os.path.exists(gt_path):
            with open(gt_path, 'r', encoding='utf-8') as f:
                gt = json.load(f)
            files.append((img_path, gt))

    random.Random(42).shuffle(files)
    split = int(len(files) * split_ratio)
    train_files = files[:split]
    test_files = files[split:]

    # Escribir label.txt para train y test
    def write_labels(files_list, subset_dir, label_path):
        with open(label_path, 'w', encoding='utf-8') as f:
            for img_path, gt in files_list:
                if os.path.exists(img_path):
                    fname = os.path.basename(img_path)
                    dst = os.path.join(subset_dir, fname)
                    try:
                        copy2(img_path, dst)
                    except IOError:
                        continue
                    # PPOCR format: image_path\ttext
                    text = gt.get("full_text", "").replace('\n', ' ')
                    f.write(f"{os.path.join(subset_dir, fname)}\t{text}\n")

    write_labels(train_files,
                 os.path.join(output_dir, "train"),
                 os.path.join(output_dir, "train", "label.txt"))
    write_labels(test_files,
                 os.path.join(output_dir, "test"),
                 os.path.join(output_dir, "test", "label.txt"))

    print(f"\n✅ Dataset PPOCR preparado en: {output_dir}")
    print(f"   • Train: {len(train_files)} imágenes → {os.path.join(output_dir, 'train', 'label.txt')}")
    print(f"   • Test:  {len(test_files)} imágenes → {os.path.join(output_dir, 'test', 'label.txt')}")
    print(f"   • split_ratio: {split_ratio}")


# ──────────────────────────────────────────────
#  Fine-tuning script
# ──────────────────────────────────────────────

def run_finetune(
    dataset_dir: str = "./ppocr_dataset",
    pretrained_model: str = "en_PP-OCRv3_rec",
    save_model_dir: str = "./finetuned_ve",
    epochs: int = 100,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    character_dict_path: Optional[str] = None,
):
    """
    Prepara y ejecuta fine-tuning de PaddleOCR para facturas VE.

    Args:
        dataset_dir: Directorio con dataset en formato PPOCR.
        pretrained_model: Modelo pre-entrenado base.
        save_model_dir: Directorio para guardar modelo fine-tuned.
        epochs: Número de épocas.
        batch_size: Tamaño de lote.
        learning_rate: Tasa de aprendizaje.
        character_dict_path: Ruta al diccionario de caracteres.
    """
    import subprocess
    import sys

    # Verificar que PaddleOCR está instalado
    try:
        import paddleocr
    except ImportError:
        print("✗ PaddleOCR no está instalado. pip install paddleocr paddlepaddle")
        return

    # Verificar dataset
    train_label = os.path.join(dataset_dir, "train", "label.txt")
    test_label = os.path.join(dataset_dir, "test", "label.txt")
    
    if not os.path.exists(train_label):
        print(f"✗ No se encuentra: {train_label}")
        print("  Ejecute primero: python -m ocr.train_ve prepare")
        return

    # Crear configuración de entrenamiento
    os.makedirs(save_model_dir, exist_ok=True)

    # Los archivos de configuración de PaddleOCR están en su
    # directorio de instalación
    config = {
        "Global": {
            "epoch_num": epochs,
            "save_model_dir": save_model_dir,
            "pretrained_model": pretrained_model,
            "character_dict_path": character_dict_path or "",
            "character_type": "en",
            "max_text_length": 100,
            "use_space_char": True,
            "save_epoch_step": 10,
            "eval_batch_step": [0, 200],
        },
        "Optimizer": {
            "name": "Adam",
            "lr": learning_rate,
        },
        "Train": {
            "dataset": {
                "name": "SimpleDataSet",
                "data_dir": os.path.join(dataset_dir, "train"),
                "label_file_list": [train_label],
            },
            "loader": {
                "shuffle": True,
                "batch_size_per_card": batch_size,
                "num_workers": 2,
            },
        },
        "Eval": {
            "dataset": {
                "name": "SimpleDataSet",
                "data_dir": os.path.join(dataset_dir, "test"),
                "label_file_list": [test_label],
            },
            "loader": {
                "shuffle": False,
                "batch_size_per_card": batch_size,
                "num_workers": 2,
            },
        },
    }

    config_path = os.path.join(save_model_dir, "config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n🏋️  Iniciando fine-tuning de PaddleOCR VE")
    print(f"   • Dataset: {dataset_dir}")
    print(f"   • Modelo base: {pretrained_model}")
    print(f"   • Épocas: {epochs}")
    print(f"   • Batch size: {batch_size}")
    print(f"   • LR: {learning_rate}")
    print(f"   • Config: {config_path}")
    print(f"   • Output: {save_model_dir}")
    print()

    # Intentar ejecutar el script de entrenamiento de PaddleOCR
    cmd = [
        sys.executable, "-m", "paddleocr.tools.train",
        "-c", config_path,
    ]

    print(f"Ejecutando: {' '.join(cmd)}")
    print("NOTA: Este proceso puede tomar horas en CPU.")
    print("      Se recomienda GPU NVIDIA con CUDA.")
    print()

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        print(f"\n✅ Fine-tuning completado. Modelo guardado en: {save_model_dir}")
    except subprocess.CalledProcessError as e:
        print(f"✗ Error en fine-tuning:")
        print(f"  Código: {e.returncode}")
        print(f"  stdout: {e.stdout[:500]}")
        print(f"  stderr: {e.stderr[:500]}")


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="πNAD — Fine-Tuning Pipeline para PaddleOCR VE",
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando")

    # generate
    gen_parser = subparsers.add_parser("generate", help="Generar dataset sintético")
    gen_parser.add_argument("--count", type=int, default=200, help="Número de facturas")
    gen_parser.add_argument("--output", type=str, default="./synthetic_data", help="Directorio de salida")
    gen_parser.add_argument("--seed", type=int, default=42, help="Semilla")
    gen_parser.add_argument("--no-images", action="store_true", help="No generar imágenes (solo texto)")

    # prepare
    prep_parser = subparsers.add_parser("prepare", help="Preparar dataset PPOCR")
    prep_parser.add_argument("--input", type=str, default="./synthetic_data", help="Directorio de entrada")
    prep_parser.add_argument("--output", type=str, default="./ppocr_dataset", help="Directorio de salida")
    prep_parser.add_argument("--split", type=float, default=0.8, help="Ratio train/test")

    # finetune
    ft_parser = subparsers.add_parser("finetune", help="Ejecutar fine-tuning")
    ft_parser.add_argument("--dataset", type=str, default="./ppocr_dataset", help="Dataset PPOCR")
    ft_parser.add_argument("--model", type=str, default="en_PP-OCRv3_rec", help="Modelo pre-entrenado")
    ft_parser.add_argument("--output", type=str, default="./finetuned_ve", help="Directorio de salida")
    ft_parser.add_argument("--epochs", type=int, default=100, help="Épocas")
    ft_parser.add_argument("--batch", type=int, default=32, help="Batch size")
    ft_parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")

    args = parser.parse_args()

    if args.command == "generate":
        generate_dataset(
            output_dir=args.output,
            count=args.count,
            seed=args.seed,
            with_images=not args.no_images,
        )
    elif args.command == "prepare":
        prepare_ppocr_format(
            input_dir=args.input,
            output_dir=args.output,
            split_ratio=args.split,
        )
    elif args.command == "finetune":
        run_finetune(
            dataset_dir=args.dataset,
            pretrained_model=args.model,
            save_model_dir=args.output,
            epochs=args.epochs,
            batch_size=args.batch,
            learning_rate=args.lr,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
