import os
import boto3
import subprocess
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
OUTPUT_BUCKET = os.getenv("S3_OUTPUT_BUCKET")

s3 = boto3.client("s3", region_name=AWS_REGION)

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
        
        # Return success back to SageMaker logic hook
        return JSONResponse(content={
            "job_id": job_id,
            "status": "STEMS_READY", 
            "stems": uploaded_stems,
            "input_bucket": input_bucket
        }, status_code=200)
        
    except Exception as e:
        print(f"Error: {str(e)}", flush=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)
