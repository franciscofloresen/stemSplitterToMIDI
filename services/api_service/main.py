import os
import uuid
import time
import boto3
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Audio2MIDI API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for testing; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment Variables
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
INPUT_BUCKET = os.getenv("INPUT_BUCKET")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "audio2midi-output")
STEM_ENDPOINT_NAME = os.getenv("STEM_ENDPOINT_NAME", "audio2midi-stem-endpoint")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "audio2midi-jobs")

# Clients
s3 = boto3.client("s3", region_name=AWS_REGION)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

class JobStatus(BaseModel):
    job_id: str
    status: str
    message: str

@app.get("/")
def read_root():
    return {"message": "Audio2MIDI API is running"}

@app.post("/upload", response_model=JobStatus)
async def upload_audio(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(('.wav', '.mp3', '.flac')):
        raise HTTPException(status_code=400, detail="Unsupported file format")

    job_id = str(uuid.uuid4())
    file_extension = os.path.splitext(file.filename)[1]
    s3_key = f"uploads/{job_id}{file_extension}"

    # 1. Create Initial Status in DynamoDB
    try:
        table.put_item(Item={
            'job_id': job_id,
            'status': 'QUEUED',
            'created_at': int(time.time()),
            'ttl': int(time.time()) + 86400 # 24 hour expiration
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize job: {str(e)}")

    # 2. Upload Audio to S3
    try:
        s3.upload_fileobj(file.file, INPUT_BUCKET, s3_key)
    except Exception as e:
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'ERROR'}
        )
        raise HTTPException(status_code=500, detail=f"Failed to upload to S3: {str(e)}")

    # 3. Create JSON payload trigger
    import json
    trigger_payload = {
        "job_id": job_id,
        "s3_key": s3_key,
        "input_bucket": INPUT_BUCKET
    }
    trigger_key = f"triggers/{job_id}_stem.json"
    
    try:
        s3.put_object(
            Bucket=INPUT_BUCKET,
            Key=trigger_key,
            Body=json.dumps(trigger_payload),
            ContentType="application/json"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create SageMaker trigger: {str(e)}")

    # 4. Invoke SageMaker Async Endpoint
    try:
        sagemaker_runtime.invoke_endpoint_async(
            EndpointName=STEM_ENDPOINT_NAME,
            InputLocation=f"s3://{INPUT_BUCKET}/{trigger_key}",
            ContentType="application/json"
        )
    except Exception as e:
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'ERROR'}
        )
        raise HTTPException(status_code=500, detail=f"Failed to trigger inference: {str(e)}")

    return JobStatus(
        job_id=job_id,
        status="QUEUED",
        message="File uploaded and inference queued successfully."
    )

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    try:
        response = table.get_item(Key={'job_id': job_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Job not found")
        
        item = response['Item']
        status = item.get('status')
        result = {
            "job_id": job_id,
            "status": status,
            "created_at": item.get('created_at'),
            "info": "Job is being processed"
        }
        
        # If completed, generate presigned URLs for downloading the results
        if status == "COMPLETED":
            result["info"] = "Job completed successfully"
            
            # Helper to generate presigned URL
            def get_presigned_url(bucket, key):
                try:
                    return s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket, 'Key': key},
                                                    ExpiresIn=3600) # 1 hour
                except Exception:
                    return None

            result["downloads"] = {
                "vocals_stem": get_presigned_url(INPUT_BUCKET, f"stems/{job_id}/vocals.wav"),
                "instrumental_stem": get_presigned_url(INPUT_BUCKET, f"stems/{job_id}/no_vocals.wav"),
                "vocals_midi": get_presigned_url(OUTPUT_BUCKET, f"outputs/{job_id}/vocals_basic_pitch.mid"),
                "instrumental_midi": get_presigned_url(OUTPUT_BUCKET, f"outputs/{job_id}/no_vocals_basic_pitch.mid")
            }
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching status: {str(e)}")
