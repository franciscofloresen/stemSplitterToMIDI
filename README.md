# 🎵 Audio2MIDI Cloud (Decoupled & Well-Architected)

## WAV → Stem Separation → MIDI Conversion Platform

Audio2MIDI Cloud is a cloud-native platform that converts audio files (WAV/MP3) into MIDI files using a distributed, decoupled microservices architecture.

---

## 🚀 Refined Architecture

The system has been updated to follow the **AWS Well-Architected Framework** more closely:

1.  **Decoupled Pipeline:** Uses two separate SQS queues (`stem-jobs` and `midi-jobs`) to prevent worker contention and ensure smooth state transitions.
2.  **Resource Optimization:** Upgraded to `t3a.medium` (AMD-based) to provide 4GB of RAM, ensuring AI libraries like `Demucs` and `Basic Pitch` don't crash due to memory limits.
3.  **Enhanced Security:** S3 buckets now have explicit Public Access Blocks, and IAM roles follow the principle of least privilege.
4.  **Cost Efficiency:** Uses S3 Lifecycle policies (24h deletion) and pay-per-request DynamoDB to keep the footprint minimal.

---

## 🏗 System Workflow

```text
      User
        |
   API Service (FastAPI)
        |
   1. Upload to S3 (Input Bucket)
   2. Push to 'stem-jobs' SQS
        |
   Stem Service (Worker)
        |
   1. Pull from 'stem-jobs'
   2. Run Demucs (AI Split)
   3. Upload Stems to S3
   4. Push to 'midi-jobs' SQS
        |
   MIDI Service (Worker)
        |
   1. Pull from 'midi-jobs'
   2. Run Basic Pitch (AI MIDI)
   3. Upload MIDI to S3 (Output Bucket)
   4. Mark Job COMPLETE in DynamoDB
```

---

## 💰 Monthly Cost Estimation (Approx. $20 USD)

| Service | Component | Estimated Cost |
| :--- | :--- | :--- |
| **EC2** | `t3a.medium` (4GB RAM) | ~$13.50 |
| **EBS** | 50GB GP3 Storage | ~$4.00 |
| **S3** | Storage & API | ~$0.50 |
| **SQS** | Messaging | $0.00 (Free Tier) |
| **DynamoDB** | Metadata | $0.00 (Free Tier) |
| **Total** | | **~$18.00 - $20.00** |

---

## 🐳 Deployment Guide

### 1. Build Multi-Platform Images
Since the EC2 instance is `amd64`, you must build images for that platform:

```bash
docker buildx build --platform linux/amd64 -t audio2midi/api_service:latest ./services/api_service --push
docker buildx build --platform linux/amd64 -t audio2midi/stem_service:latest ./services/stem_service --push
docker buildx build --platform linux/amd64 -t audio2midi/midi_service:latest ./services/midi_service --push
```

### 2. Infrastructure
```bash
cd terraform
terraform init
terraform apply
```

### 3. Kubernetes
Update `k8s/config.yaml` with the outputs from Terraform, then:
```bash
KUBECONFIG=kubeconfig.yaml kubectl apply -f k8s/
```

---

## 🛠 Tech Stack
- **Infrastructure:** Terraform, Kubernetes (k3s on EC2)
- **AI/ML:** Demucs (Meta), Basic Pitch (Spotify)
- **Backend:** FastAPI, Boto3
- **Cloud:** AWS (S3, SQS, DynamoDB, IAM)
