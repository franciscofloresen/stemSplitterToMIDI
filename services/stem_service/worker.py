import os
import json
import boto3
import subprocess
from pathlib import Path

# Config
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
INPUT_BUCKET = os.getenv("INPUT_BUCKET")
STEM_QUEUE_URL = os.getenv("STEM_QUEUE_URL")
MIDI_QUEUE_URL = os.getenv("MIDI_QUEUE_URL")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "audio2midi-jobs")

# Clients
s3 = boto3.client("s3", region_name=AWS_REGION)
sqs = boto3.client("sqs", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

def update_job_status(job_id, status):
    try:
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': status}
        )
    except Exception as e:
        print(f"Failed to update DynamoDB for {job_id}: {e}", flush=True)

def process_message(message):
    receipt_handle = message['ReceiptHandle']
    attributes = message.get('MessageAttributes', {})
    
    # Check MessageType
    msg_type = attributes.get('MessageType', {}).get('StringValue')
    if msg_type != 'AUDIO_UPLOAD':
        return False

    job_id = attributes.get('JobId', {}).get('StringValue')
    s3_key = attributes.get('S3Key', {}).get('StringValue')
    
    if not job_id or not s3_key:
        return False

    print(f"Processing Job: {job_id} | File: {s3_key}", flush=True)
    update_job_status(job_id, "SPLITTING")

    local_input = f"/tmp/{job_id}_input"
    output_dir = f"/tmp/{job_id}_output"
    os.makedirs(output_dir, exist_ok=True)

    try:
        # 1. Download from S3
        s3.download_file(INPUT_BUCKET, s3_key, local_input)

        # 2. Run Demucs (don't use check=True — torchaudio warnings can cause non-zero exit)
        result = subprocess.run([
            "demucs", 
            "--two-stems", "vocals",
            "-o", output_dir,
            local_input
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Demucs exited with code {result.returncode}", flush=True)
            print(f"stderr: {result.stderr[-500:]}", flush=True)
        
        # Verify output files exist
        base_name = os.path.basename(local_input)
        processed_path = Path(output_dir) / "htdemucs" / base_name
        vocals_path = processed_path / "vocals.wav"
        no_vocals_path = processed_path / "no_vocals.wav"
        
        if not vocals_path.exists() or not no_vocals_path.exists():
            raise FileNotFoundError(f"Demucs did not produce expected stems at {processed_path}")

        # 3. Upload Stems to S3
        for stem in ["vocals.wav", "no_vocals.wav"]:
            stem_path = processed_path / stem
            if stem_path.exists():
                s3_stem_key = f"stems/{job_id}/{stem}"
                s3.upload_file(str(stem_path), INPUT_BUCKET, s3_stem_key)

        # 4. Update Status and Notify MIDI service
        update_job_status(job_id, "STEMS_READY")
        sqs.send_message(
            QueueUrl=MIDI_QUEUE_URL,
            MessageAttributes={
                'JobId': {'DataType': 'String', 'StringValue': job_id},
                'MessageType': {'DataType': 'String', 'StringValue': 'STEMS_READY'}
            },
            MessageBody=f"Stems ready: {job_id}"
        )

        # 5. Cleanup
        sqs.delete_message(QueueUrl=STEM_QUEUE_URL, ReceiptHandle=receipt_handle)
        return True

    except Exception as e:
        print(f"Error processing {job_id}: {str(e)}", flush=True)
        update_job_status(job_id, "ERROR")
        return False
    finally:
        if os.path.exists(local_input): os.remove(local_input)

def main():
    print("Stem Service Worker started. Polling SQS...")
    while True:
        response = sqs.receive_message(
            QueueUrl=STEM_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            MessageAttributeNames=['All']
        )

        messages = response.get('Messages', [])
        for msg in messages:
            process_message(msg)

if __name__ == "__main__":
    main()
