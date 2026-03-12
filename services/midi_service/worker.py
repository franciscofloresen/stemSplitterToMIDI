import os
import boto3
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH
from pathlib import Path

# Config
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
INPUT_BUCKET = os.getenv("INPUT_BUCKET")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET")
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
    
    msg_type = attributes.get('MessageType', {}).get('StringValue')
    if msg_type != 'STEMS_READY':
        return False

    job_id = attributes.get('JobId', {}).get('StringValue')
    if not job_id:
        return False

    print(f"MIDI Conversion for Job: {job_id}", flush=True)
    update_job_status(job_id, "CONVERTING")

    local_stems_dir = f"/tmp/{job_id}_stems"
    local_midi_dir = f"/tmp/{job_id}_midi"
    os.makedirs(local_stems_dir, exist_ok=True)
    os.makedirs(local_midi_dir, exist_ok=True)

    try:
        stems_to_process = ["vocals.wav", "no_vocals.wav"]
        for stem in stems_to_process:
            s3_stem_key = f"stems/{job_id}/{stem}"
            local_stem_path = f"{local_stems_dir}/{stem}"
            s3.download_file(INPUT_BUCKET, s3_stem_key, local_stem_path)

            print(f"Processing stem: {stem}", flush=True)
            predict_and_save(
                audio_path_list=[local_stem_path],
                output_directory=local_midi_dir,
                save_midi=True,
                sonify_midi=False,
                save_model_outputs=False,
                save_notes=False,
                model_or_model_path=ICASSP_2022_MODEL_PATH
            )

        for midi_file in Path(local_midi_dir).glob("*.mid"):
            s3_midi_key = f"outputs/{job_id}/{midi_file.name}"
            s3.upload_file(str(midi_file), OUTPUT_BUCKET, s3_midi_key)

        update_job_status(job_id, "COMPLETED")
        sqs.delete_message(QueueUrl=MIDI_QUEUE_URL, ReceiptHandle=receipt_handle)
        return True

    except Exception as e:
        print(f"Error converting {job_id} to MIDI: {str(e)}", flush=True)
        update_job_status(job_id, "ERROR")
        return False
    finally:
        import shutil
        shutil.rmtree(local_stems_dir, ignore_errors=True)
        shutil.rmtree(local_midi_dir, ignore_errors=True)

def main():
    print("MIDI Service Worker started. Polling SQS...", flush=True)
    while True:
        response = sqs.receive_message(
            QueueUrl=MIDI_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            MessageAttributeNames=['All']
        )

        messages = response.get('Messages', [])
        for msg in messages:
            process_message(msg)

if __name__ == "__main__":
    main()
