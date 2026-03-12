const API_URL = "http://52.70.122.89";

// UI Elements
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const selectedFileDiv = document.getElementById("selected-file");
const fileNameSpan = document.getElementById("file-name");
const clearBtn = document.getElementById("clear-btn");
const uploadBtn = document.getElementById("upload-btn");

const uploadPanel = document.getElementById("upload-panel");
const statusPanel = document.getElementById("status-panel");
const resultsPanel = document.getElementById("results-panel");
const resetBtn = document.getElementById("reset-btn");

const stepQueued = document.getElementById("step-queued");
const stepSplitting = document.getElementById("step-splitting");
const stepConverting = document.getElementById("step-converting");
const progressFill = document.getElementById("progress-fill");
const statusMessage = document.getElementById("status-message");

let currentFile = null;
let pollInterval = null;

// Drag and drop setup
dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) handleFile(e.target.files[0]);
});

function handleFile(file) {
    if (!file.name.match(/\.(wav|mp3|flac)$/i)) {
        alert("Please upload a .wav, .mp3, or .flac file.");
        return;
    }
    currentFile = file;
    fileNameSpan.innerText = file.name;
    dropZone.style.display = "none";
    selectedFileDiv.style.display = "flex";
    uploadBtn.disabled = false;
}

clearBtn.addEventListener("click", () => {
    currentFile = null;
    fileInput.value = "";
    dropZone.style.display = "block";
    selectedFileDiv.style.display = "none";
    uploadBtn.disabled = true;
});

// Upload Logic
uploadBtn.addEventListener("click", async () => {
    if (!currentFile) return;
    
    uploadBtn.classList.add("loading");
    uploadBtn.disabled = true;
    
    try {
        const formData = new FormData();
        formData.append("file", currentFile);
        
        const res = await fetch(`${API_URL}/upload`, { method: "POST", body: formData });
        if (!res.ok) throw new Error("Upload failed");
        
        const data = await res.json();
        startPolling(data.job_id);
        
    } catch (e) {
        alert("Upload failed: " + e.message);
        uploadBtn.classList.remove("loading");
        uploadBtn.disabled = false;
    }
});

// Polling Logic
function startPolling(jobId) {
    uploadPanel.classList.add("hidden");
    statusPanel.classList.remove("hidden");
    
    progressFill.style.width = "5%";
    statusMessage.innerText = "Initializing processors...";

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_URL}/status/${jobId}`);
            if (!res.ok) throw new Error("Failed to get status");
            const data = await res.json();
            
            updateUIState(data);
            
            if (data.status === "COMPLETED") {
                clearInterval(pollInterval);
                showResults(data.downloads);
            } else if (data.status === "ERROR") {
                clearInterval(pollInterval);
                statusMessage.innerText = "Internal processing error occurred.";
                statusMessage.style.color = "var(--danger)";
            }
            
        } catch (e) {
            console.error(e);
        }
    }, 5000); // Check every 5s
}

function updateUIState(data) {
    statusMessage.innerText = "Hang tight, AI is splitting audio... (~5 mins)";
    
    if (data.status === "QUEUED") {
        progressFill.style.width = "10%";
    } else if (data.status === "SPLITTING") {
        progressFill.style.width = "40%";
        stepQueued.className = "done";
        stepSplitting.className = "active";
        statusMessage.innerText = "Demucs is separating Vocals & Instrumental... (~7 mins)";
    } else if (data.status === "STEMS_READY" || data.status === "CONVERTING") {
        progressFill.style.width = "80%";
        stepQueued.className = "done";
        stepSplitting.className = "done";
        stepConverting.className = "active";
        statusMessage.innerText = "Basic Pitch is extracting MIDI notes... (~30 secs)";
    } else if (data.status === "COMPLETED") {
        progressFill.style.width = "100%";
        stepConverting.className = "done";
    }
}

function showResults(downloads) {
    statusPanel.classList.add("hidden");
    resultsPanel.classList.remove("hidden");
    
    // Set Download Links
    document.getElementById("dl-vocals-wav").href = downloads.vocals_stem;
    document.getElementById("dl-vocals-midi").href = downloads.vocals_midi;
    document.getElementById("dl-inst-wav").href = downloads.instrumental_stem;
    document.getElementById("dl-inst-midi").href = downloads.instrumental_midi;
}

resetBtn.addEventListener("click", () => {
    // Reset State
    currentFile = null;
    fileInput.value = "";
    dropZone.style.display = "block";
    selectedFileDiv.style.display = "none";
    uploadBtn.disabled = true;
    uploadBtn.classList.remove("loading");
    
    stepQueued.className = "active";
    stepSplitting.className = "";
    stepConverting.className = "";
    progressFill.style.width = "0%";
    
    resultsPanel.classList.add("hidden");
    uploadPanel.classList.remove("hidden");
});
