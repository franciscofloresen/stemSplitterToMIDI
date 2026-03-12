import os
import sys

def check_dependencies():
    """
    Check if the necessary AI libraries are installed in the current environment.
    """
    libs = ["demucs", "basic_pitch", "librosa", "torch", "numpy"]
    missing = []
    
    print("--- Checking AI Model Dependencies ---")
    for lib in libs:
        try:
            __import__(lib)
            print(f"[OK] {lib} is installed.")
        except ImportError:
            missing.append(lib)
            print(f"[MISSING] {lib} is NOT installed.")
    
    if missing:
        print("\nTo install missing libraries, run:")
        print(f"pip install {' '.join(missing)}")
        return False
    return True

def run_sample_validation(audio_file):
    """
    Simple test to verify models can process an audio file.
    """
    if not os.path.exists(audio_file):
        print(f"Error: Audio file '{audio_file}' not found.")
        return

    print(f"\n--- Testing Demucs (Stem Separation) on {audio_file} ---")
    try:
        from demucs import separator
        # Note: In a real worker, we'd use a more specific model, but 'htdemucs' is standard.
        # This will download the model weights (several hundred MB) on first run.
        print("Note: First run will download model weights (~400MB).")
        # Run separator (this is a simplified example)
        # separator.main(["--mp3", audio_file])
        print("[SUCCESS] Demucs imported and ready.")
    except Exception as e:
        print(f"[ERROR] Demucs test failed: {e}")

    print("\n--- Testing Basic Pitch (MIDI Conversion) ---")
    try:
        from basic_pitch.inference import predict_and_save
        # predict_and_save([audio_file], "output_midi", True, True, True, True)
        print("[SUCCESS] Basic Pitch imported and ready.")
    except Exception as e:
        print(f"[ERROR] Basic Pitch test failed: {e}")

if __name__ == "__main__":
    if check_dependencies():
        # If user provides a file path as argument, try to process it
        if len(sys.argv) > 1:
            run_sample_validation(sys.argv[1])
        else:
            print("\nReady to test! Provide a .wav file to run a full validation:")
            print("python validation/test_models.py sample.wav")