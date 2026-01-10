import sys
import traceback

print("--- WORKER STARTING ---", flush=True)

try:
    print("Importing dependencies...", flush=True)
    import runpod
    import torch
    import os
    import requests
    import tempfile

    # Fix for PyTorch 2.6+ weights_only=True default
    # CRITICAL: Patch torch.load BEFORE importing whisperx
    # Libraries cache torch.load reference during import, so patch must come first
    print("Patching torch.load for trusted model loading...", flush=True)
    _original_torch_load = torch.load

    def patched_torch_load(*args, **kwargs):
        # Force weights_only=False for trusted model sources
        # Override even if explicitly set to True by libraries
        kwargs['weights_only'] = False
        return _original_torch_load(*args, **kwargs)

    torch.load = patched_torch_load
    print("torch.load patched successfully.", flush=True)

    # Now import whisperx after patching torch.load
    import whisperx
    print("Imports successful.", flush=True)

    # Global model variable for warm starts
    model = None
    diarize_model = None
    device = "cuda"
    batch_size = 16 # reduce if low GPU memory
    compute_type = "float16" # "float16" or "int8"

    def load_models():
        global model, diarize_model
        
        # 1. Load Whisper Model
        # Large-v2 or v3 are recommended. v3 is latest.
        print("Loading WhisperX model...", flush=True)
        try:
            model = whisperx.load_model("large-v3", device, compute_type=compute_type)
        except Exception as e:
            print(f"CRITICAL: Failed to load Whisper Model: {e}", flush=True)
            raise e

        # 2. Load Diarization Model
        # Requires HuggingFace token. We check for it in env vars or input.
        hf_token = os.environ.get("HF_TOKEN")
        if hf_token:
            print("Loading Diarization model...", flush=True)
            try:
                diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
            except Exception as e:
                 print(f"WARNING: Failed to load Diarization Model: {e}", flush=True)
                 # We don't raise here to allow basic transcription to work
        else:
            print("No HF_TOKEN provided. Diarization disabled.", flush=True)

    def download_file(url, local_path):
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    def handler(job):
        """ Handler function that will be used to process jobs. """
        print(f"Received job: {job['id']}", flush=True)
        job_input = job['input']
        
        # Extract inputs
        audio_url = job_input.get('audio_url')
        if not audio_url:
            return {"error": "Missing 'audio_url' in input"}
        
        # Optional auth token override
        req_hf_token = job_input.get('hf_token')
        
        # Optional speaker count hint
        min_speakers = job_input.get('min_speakers')
        max_speakers = job_input.get('max_speakers')

        print(f"Processing audio: {audio_url}", flush=True)

        # Use a temp directory for the file
        with tempfile.TemporaryDirectory() as tmpdirname:
            audio_path = os.path.join(tmpdirname, "audio.mp3") # Extension might vary, ffmpeg handles it
            
            try:
                download_file(audio_url, audio_path)
            except Exception as e:
                return {"error": f"Failed to download audio: {str(e)}"}

            # 1. Transcribe
            print("Transcribing...", flush=True)
            audio = whisperx.load_audio(audio_path)
            result = model.transcribe(audio, batch_size=batch_size)
            
            # 2. Align
            print("Aligning...", flush=True)
            model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
            result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
            
            # 3. Diarize
            # Check if we need to load or use provided token
            current_diarize_model = diarize_model
            
            # If token provided in request but model not loaded globally
            if not current_diarize_model and req_hf_token:
                 print("Loading Diarization model (request-scoped)...", flush=True)
                 current_diarize_model = whisperx.DiarizationPipeline(use_auth_token=req_hf_token, device=device)
            
            if current_diarize_model:
                print("Diarizing...", flush=True)
                diarize_segments = current_diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers)
                result = whisperx.assign_word_speakers(diarize_segments, result)
            else:
                print("Skipping diarization (no token).", flush=True)

        # Cleanup is automatic via tempfile, but we return the full JSON result
        return result

    # Initialize the model on container start
    if torch.cuda.is_available():
        print("CUDA available. Initializing models...", flush=True)
        load_models()
    else:
        print("CUDA NOT AVAILABLE! Check Docker/Driver settings.", flush=True)

    print("Starting Serverless Handler...", flush=True)
    runpod.serverless.start({"handler": handler})

except Exception as e:
    print(f"CRITICAL ERROR DURING STARTUP: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
