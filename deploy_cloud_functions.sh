#!/bin/bash

# Deploy Script for NAD Scanner to Google Cloud Functions
# Usage: ./deploy_cloud_functions.sh

set -e

# Configuration
PROJECT_ID="nadscanner-production"
REGION="us-central1"
FUNCTION_NAME="nadscanner-api"
RUNTIME="python39"
MEMORY="2GB"
TIMEOUT="540s"

echo "🚀 Deploying NAD Scanner to Google Cloud Functions..."

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI not found. Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Set project
echo "📋 Setting project to: $PROJECT_ID"
gcloud config set project $PROJECT_ID

# Enable required APIs
echo "🔧 Enabling required APIs..."
gcloud services enable \
    drive.googleapis.com \
    cloudfunctions.googleapis.com \
    cloudresourcemanager.googleapis.com \
    appengine.googleapis.com \
    iam.googleapis.com \
    logging.googleapis.com \
    monitoring.googleapis.com

# Deploy function
echo "📦 Deploying Cloud Function..."
gcloud functions deploy $FUNCTION_NAME \
    --runtime $RUNTIME \
    --trigger-http \
    --allow-unauthenticated \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --region $REGION \
    --env-vars-file cloud_functions/.env.yaml \
    --source cloud_functions/

# Get function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --format="value(httpsTrigger.url)")

echo "✅ Deployment complete!"
echo "🌐 Function URL: $FUNCTION_URL"
echo "🌐 App Domain: https://negocioaldia.app"
echo ""
echo "📝 Next steps:"
echo "1. Test the function: curl $FUNCTION_URL/health_check"
echo "2. Configure Google Sites to call: $FUNCTION_URL"
echo "3. Set up custom domain: negocioaldia.app in Google Workspace"
