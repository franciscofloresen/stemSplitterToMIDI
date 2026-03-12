import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Set mock environment variables BEFORE importing the app
os.environ["INPUT_BUCKET"] = "test-input-bucket"
os.environ["STEM_QUEUE_URL"] = "https://test-stem-queue-url"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["DYNAMODB_TABLE"] = "test-jobs"

# Mock boto3 before the app module creates real clients
with patch("boto3.client") as mock_client, \
     patch("boto3.resource") as mock_resource:

    # Configure DynamoDB mock
    mock_table = MagicMock()
    mock_dynamo = MagicMock()
    mock_dynamo.Table.return_value = mock_table
    mock_resource.return_value = mock_dynamo

    from services.api_service.main import app

client = TestClient(app)


@pytest.fixture
def mock_aws():
    with patch("services.api_service.main.s3") as mock_s3, \
         patch("services.api_service.main.sqs") as mock_sqs, \
         patch("services.api_service.main.table") as mock_table:
        yield mock_s3, mock_sqs, mock_table


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Audio2MIDI API is running"}


def test_upload_unsupported_file():
    files = {"file": ("test.txt", b"some text content", "text/plain")}
    response = client.post("/upload", files=files)
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file format"


def test_upload_success(mock_aws):
    mock_s3, mock_sqs, mock_table = mock_aws

    mock_s3.upload_fileobj.return_value = True
    mock_sqs.send_message.return_value = {"MessageId": "123"}
    mock_table.put_item.return_value = True

    files = {"file": ("test.wav", b"fake wav content", "audio/wav")}
    response = client.post("/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "QUEUED"
    assert "job_id" in data

    # Verify all three AWS services were called
    assert mock_table.put_item.called
    assert mock_s3.upload_fileobj.called
    assert mock_sqs.send_message.called


def test_status_job_not_found(mock_aws):
    _, _, mock_table = mock_aws
    mock_table.get_item.return_value = {}  # No 'Item' key = not found

    response = client.get("/status/nonexistent-job-id")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_status_job_found(mock_aws):
    _, _, mock_table = mock_aws
    mock_table.get_item.return_value = {
        "Item": {
            "job_id": "test-job-123",
            "status": "QUEUED",
            "created_at": 1234567890
        }
    }

    response = client.get("/status/test-job-123")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "QUEUED"
    assert data["job_id"] == "test-job-123"
