"""
Main entry point for Google Cloud Functions
NAD Scanner - Invoice Processing System
"""

import os
import json
import functions_framework
from flask import Flask, request, jsonify
from flask_cors import CORS

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Import modules (lazy loading for cold start optimization)
def get_billing_modules():
    """Lazy load billing modules"""
    from billing import (
        PlanManager,
        init_billing_db,
        create_subscription,
        create_invoice,
        create_local_payment,
        BillingAnalytics
    )
    return {
        'PlanManager': PlanManager,
        'init_billing_db': init_billing_db,
        'create_subscription': create_subscription,
        'create_invoice': create_invoice,
        'create_local_payment': create_local_payment,
        'BillingAnalytics': BillingAnalytics
    }

def get_ocr_modules():
    """Lazy load OCR modules"""
    from ocr import OCREngine
    from ocr.extractor import InvoiceParser
    return {
        'OCREngine': OCREngine,
        'InvoiceParser': InvoiceParser
    }

def get_drive_modules():
    """Lazy load Drive modules"""
    from drive.uploader import DriveUploader
    return {
        'DriveUploader': DriveUploader
    }


@functions_framework.http
def health_check(request):
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "nadscanner-cloud-functions",
        "version": "1.0.0"
    }), 200


@functions_framework.http
def process_invoice(request):
    """
    Process invoice from uploaded image
    Main OCR processing endpoint
    """
    try:
        # Parse request
        request_json = request.get_json(silent=True)
        
        if not request_json or 'image_data' not in request_json:
            return jsonify({
                "error": "Missing image_data in request"
            }), 400
        
        image_data = request_json['image_data']
        tenant_id = request_json.get('tenant_id')
        capture_mode = request_json.get('capture_mode', 'factura')
        
        # Get OCR modules
        ocr_modules = get_ocr_modules()
        
        # Initialize OCR engine
        engine = ocr_modules['OCREngine']()
        parser = ocr_modules['InvoiceParser']()
        
        # Process image (placeholder - actual implementation needs image processing)
        # This would need the full image processing pipeline
        
        return jsonify({
            "status": "success",
            "invoice_data": {
                "numero_factura": "TEST-001",
                "rif_emisor": "J-12345678-9",
                "fecha": "2026-08-01",
                "total": 100.00
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@functions_framework.http
def get_plans(request):
    """Get available billing plans"""
    try:
        billing_modules = get_billing_modules()
        plan_manager = billing_modules['PlanManager']()
        
        plans = plan_manager.get_all_plans()
        
        return jsonify({
            "status": "success",
            "plans": plans
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@functions_framework.http
def create_subscription_cf(request):
    """Create new subscription via Cloud Function"""
    try:
        request_json = request.get_json(silent=True)
        
        if not request_json:
            return jsonify({"error": "Missing request data"}), 400
        
        billing_modules = get_billing_modules()
        
        # Initialize database
        billing_modules['init_billing_db']()
        
        # Create subscription
        subscription = billing_modules['create_subscription'](request_json)
        
        return jsonify({
            "status": "success",
            "subscription": subscription
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@functions_framework.http
def upload_to_drive(request):
    """Upload file to Google Drive"""
    try:
        request_json = request.get_json(silent=True)
        
        if not request_json or 'file_data' not in request_json:
            return jsonify({"error": "Missing file_data"}), 400
        
        drive_modules = get_drive_modules()
        uploader = drive_modules['DriveUploader']()
        
        # Upload to Drive
        result = uploader.upload_file(
            file_data=request_json['file_data'],
            filename=request_json.get('filename', 'invoice.pdf'),
            folder_id=request_json.get('folder_id')
        )
        
        return jsonify({
            "status": "success",
            "file_id": result.get('file_id'),
            "web_view_link": result.get('web_view_link')
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@functions_framework.http
def get_analytics(request):
    """Get billing analytics"""
    try:
        billing_modules = get_billing_modules()
        
        # Initialize database
        billing_modules['init_billing_db']()
        
        analytics = billing_modules['BillingAnalytics']()
        comprehensive = analytics.get_comprehensive_analytics()
        
        return jsonify({
            "status": "success",
            "analytics": comprehensive
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


# For local testing
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
