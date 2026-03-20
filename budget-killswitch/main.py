"""Cloud Function: Budget Kill Switch for Cloud Run.

Receives Pub/Sub messages from GCP Billing budget alerts.
When cost exceeds the budget amount, disables the Cloud Run service
by setting max instances to 0.
"""

import base64
import json
import os

from google.cloud.run_v2 import ServicesClient
from google.cloud.run_v2.types import Service


def budget_kill_switch(event, context):
    """Entry point for the Cloud Function.

    Args:
        event: Pub/Sub message payload.
        context: Cloud Function event metadata.
    """
    pubsub_data = base64.b64decode(event["data"]).decode("utf-8")
    notification = json.loads(pubsub_data)

    cost_amount = notification.get("costAmount", 0)
    budget_amount = notification.get("budgetAmount", 0)
    threshold_exceeded = notification.get("alertThresholdExceeded")

    print(
        f"Budget notification: cost={cost_amount}, "
        f"budget={budget_amount}, threshold={threshold_exceeded}"
    )

    if budget_amount == 0:
        print("Budget amount is 0, skipping.")
        return

    if cost_amount < budget_amount:
        print(
            f"Cost ({cost_amount}) is under budget ({budget_amount}). "
            "No action taken."
        )
        return

    print(f"Cost ({cost_amount}) exceeds budget ({budget_amount}). Disabling service.")
    _disable_cloud_run_service()


def _disable_cloud_run_service():
    """Set the Cloud Run service's max instance count to 0."""
    project = os.environ["GCP_PROJECT"]
    service_name = os.environ["CLOUD_RUN_SERVICE"]
    region = os.environ["CLOUD_RUN_REGION"]

    client = ServicesClient()
    name = f"projects/{project}/locations/{region}/services/{service_name}"

    service = client.get_service(name=name)
    service.template.scaling.max_instance_count = 0

    update_request = {"service": service, "allow_missing": False}
    operation = client.update_service(request=update_request)
    result = operation.result()

    print(
        f"Service {service_name} disabled. "
        f"Max instances set to 0. Revision: {result.latest_ready_revision}"
    )
