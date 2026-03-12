import os
import sys
import time
import requests
from pathlib import Path

API_URL = "http://52.70.122.89"
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")

def download_file(url, dest_path):
    print(f"Downloading {os.path.basename(dest_path)}...")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print(f"✅ Saved to {dest_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python auto_download.py <path_to_audio_file>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)

    # 1. Upload the file
    print(f"Uploading {file_path} to {API_URL}...")
    with open(file_path, 'rb') as f:
        response = requests.post(f"{API_URL}/upload", files={"file": f})
    
    if response.status_code != 200:
        print(f"Upload failed: {response.text}")
        sys.exit(1)

    data = response.json()
    job_id = data.get("job_id")
    print(f"Upload successful. Job ID: {job_id}")

    # 2. Poll for status
    print("Waiting for processing to complete. This may take 5-10 minutes depending on file size...")
    
    while True:
        status_res = requests.get(f"{API_URL}/status/{job_id}")
        if status_res.status_code != 200:
            print(f"Failed to check status: {status_res.text}")
            time.sleep(10)
            continue
            
        status_data = status_res.json()
        status = status_data.get("status")
        
        print(f"[{time.strftime('%H:%M:%S')}] Status: {status}")
        
        if status == "COMPLETED":
            downloads = status_data.get("downloads", {})
            break
        elif status == "ERROR":
            print("Job failed during processing on the server.")
            sys.exit(1)
            
        time.sleep(10)

    # 3. Download the files
    print("\nProcessing completed! Downloading files...")
    job_dir = Path(DOWNLOADS_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    download_tasks = [
        ("Vocals Stem", downloads.get("vocals_stem"), "vocals.wav"),
        ("Instrumental Stem", downloads.get("instrumental_stem"), "no_vocals.wav"),
        ("Vocals MIDI", downloads.get("vocals_midi"), "vocals_basic_pitch.mid"),
        ("Instrumental MIDI", downloads.get("instrumental_midi"), "no_vocals_basic_pitch.mid"),
    ]

    for name, url, filename in download_tasks:
        if url:
            dest_path = job_dir / filename
            download_file(url, dest_path)
        else:
            print(f"❌ Warning: No download URL provided for {name}")

    print(f"\n🎉 All files downloaded successfully to: {job_dir}")

if __name__ == "__main__":
    main()
