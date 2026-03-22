import os
import boto3
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import shutil

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
        stems = data.get("stems", {})
        input_bucket = data.get("input_bucket")
        
        if not job_id or not stems or not input_bucket:
            return JSONResponse(content={"error": "Missing payload data"}, status_code=400)
            
        print(f"MIDI Conversion for Job: {job_id}", flush=True)

        local_stems_dir = f"/tmp/{job_id}_stems"
        local_midi_dir = f"/tmp/{job_id}_midi"
        os.makedirs(local_stems_dir, exist_ok=True)
        os.makedirs(local_midi_dir, exist_ok=True)
        
        uploaded_midis = {}
        for stem_name, s3_stem_key in stems.items():
            local_stem_path = f"{local_stems_dir}/{stem_name}"
            s3.download_file(input_bucket, s3_stem_key, local_stem_path)

            print(f"Processing stem: {stem_name}", flush=True)
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
            uploaded_midis[midi_file.name] = s3_midi_key
            
        shutil.rmtree(local_stems_dir, ignore_errors=True)
        shutil.rmtree(local_midi_dir, ignore_errors=True)
        
        return JSONResponse(content={
            "job_id": job_id,
            "status": "COMPLETED", 
            "midis": uploaded_midis
        }, status_code=200)

    except Exception as e:
        print(f"Error converting {job_id} to MIDI: {str(e)}", flush=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)
