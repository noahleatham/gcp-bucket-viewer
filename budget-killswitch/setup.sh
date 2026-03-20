#!/usr/bin/env bash
# Setup script for the Budget Kill Switch Cloud Function.
#
# Prerequisites:
#   - gcloud CLI authenticated with appropriate permissions
#   - Billing account linked to the project
#
# Usage:
#   Edit the variables below, then run:
#   chmod +x setup.sh && ./setup.sh

set -euo pipefail

# --- Configuration ---
PROJECT_ID="${GCP_PROJECT:?Set GCP_PROJECT env var}"
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:?Set CLOUD_RUN_SERVICE env var}"
CLOUD_RUN_REGION="${CLOUD_RUN_REGION:?Set CLOUD_RUN_REGION env var}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:?Set BILLING_ACCOUNT env var}"

TOPIC_NAME="budget-kill-switch"
FUNCTION_NAME="budget-kill-switch"
BUDGET_AMOUNT="${BUDGET_AMOUNT:-10}"  # USD, default $10

# --- 1. Create Pub/Sub topic ---
echo "Creating Pub/Sub topic: ${TOPIC_NAME}"
gcloud pubsub topics create "${TOPIC_NAME}" \
  --project="${PROJECT_ID}" \
  2>/dev/null || echo "Topic already exists."

# --- 2. Create billing budget linked to the topic ---
echo "Creating billing budget (${BUDGET_AMOUNT} USD) linked to topic."
echo ""
echo "NOTE: Budget creation via gcloud is limited. Create or verify the budget"
echo "in the Cloud Console:"
echo "  https://console.cloud.google.com/billing/${BILLING_ACCOUNT}/budgets"
echo ""
echo "Settings to configure:"
echo "  - Budget amount: \$${BUDGET_AMOUNT}"
echo "  - Alert thresholds: 50%, 90%, 100%"
echo "  - Connect Pub/Sub topic: projects/${PROJECT_ID}/topics/${TOPIC_NAME}"
echo ""

# --- 3. Deploy the Cloud Function ---
echo "Deploying Cloud Function: ${FUNCTION_NAME}"
gcloud functions deploy "${FUNCTION_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${CLOUD_RUN_REGION}" \
  --runtime=python311 \
  --trigger-topic="${TOPIC_NAME}" \
  --entry-point=budget_kill_switch \
  --source="$(dirname "$0")" \
  --set-env-vars="GCP_PROJECT=${PROJECT_ID},CLOUD_RUN_SERVICE=${CLOUD_RUN_SERVICE},CLOUD_RUN_REGION=${CLOUD_RUN_REGION}" \
  --memory=256MB \
  --timeout=120s

# --- 4. Grant Cloud Run Admin to the function's service account ---
FUNCTION_SA="${PROJECT_ID}@appspot.gserviceaccount.com"
echo "Granting roles/run.admin to ${FUNCTION_SA} on service ${CLOUD_RUN_SERVICE}"
gcloud run services add-iam-policy-binding "${CLOUD_RUN_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${CLOUD_RUN_REGION}" \
  --member="serviceAccount:${FUNCTION_SA}" \
  --role="roles/run.admin"

echo ""
echo "Setup complete. Test with:"
echo "  gcloud pubsub topics publish ${TOPIC_NAME} \\"
echo "    --message='{\"budgetAmount\": ${BUDGET_AMOUNT}, \"costAmount\": $((BUDGET_AMOUNT + 5)), \"alertThresholdExceeded\": 1.0}'"
