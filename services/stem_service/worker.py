import os
import boto3
import subprocess
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json

app = FastAPI()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
OUTPUT_BUCKET = os.getenv("S3_OUTPUT_BUCKET")
MIDI_ENDPOINT_NAME = os.getenv("MIDI_ENDPOINT_NAME", "audio2midi-midi-endpoint")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "audio2midi-jobs")

s3 = boto3.client("s3", region_name=AWS_REGION)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

@app.get("/ping")
def ping():
    return JSONResponse(content={"status": "ok"}, status_code=200)

@app.post("/invocations")
async def invocations(request: Request):
    try:
        data = await request.json()
        job_id = data.get("job_id")
        s3_key = data.get("s3_key")
        input_bucket = data.get("input_bucket")
        
        if not job_id or not s3_key or not input_bucket:
            return JSONResponse(content={"error": "Missing payload data"}, status_code=400)
            
        print(f"Processing Job: {job_id} | File: {s3_key}", flush=True)
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'SPLITTING_STEMS'}
        )

        local_input = f"/tmp/{job_id}_input"
        output_dir = f"/tmp/{job_id}_output"
        os.makedirs(output_dir, exist_ok=True)
        
        s3.download_file(input_bucket, s3_key, local_input)
        
        result = subprocess.run([
            "demucs", 
            "--two-stems", "vocals",
            "-o", output_dir,
            local_input
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Demucs Error: {result.stderr[-500:]}", flush=True)
            table.update_item(
                Key={'job_id': job_id},
                UpdateExpression="set #s = :s",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':s': 'ERROR'}
            )
            return JSONResponse(content={"error": "Demucs failure"}, status_code=500)
            
        base_name = os.path.basename(local_input)
        processed_path = Path(output_dir) / "htdemucs" / base_name
        
        uploaded_stems = {}
        for stem in ["vocals.wav", "no_vocals.wav"]:
            stem_path = processed_path / stem
            if stem_path.exists():
                s3_stem_key = f"stems/{job_id}/{stem}"
                s3.upload_file(str(stem_path), OUTPUT_BUCKET, s3_stem_key)
                uploaded_stems[stem] = s3_stem_key
                
        if os.path.exists(local_input): os.remove(local_input)
        
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'STEMS_READY'}
        )

        # Trigger MIDI inference seamlessly
        trigger_payload = {
            "job_id": job_id,
            "stems": uploaded_stems,
            "input_bucket": OUTPUT_BUCKET
        }
        trigger_key = f"triggers/{job_id}_midi.json"
        
        s3.put_object(
            Bucket=input_bucket,
            Key=trigger_key,
            Body=json.dumps(trigger_payload),
            ContentType="application/json"
        )

        sagemaker_runtime.invoke_endpoint_async(
            EndpointName=MIDI_ENDPOINT_NAME,
            InputLocation=f"s3://{input_bucket}/{trigger_key}",
            ContentType="application/json"
        )
        
        return JSONResponse(content={
            "job_id": job_id,
            "status": "STEMS_READY"
        }, status_code=200)
        
    except Exception as e:
        print(f"Error: {str(e)}", flush=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)
