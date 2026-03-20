provider "aws" {
  region = var.aws_region
}

# --- 1. S3 Buckets --- #

# Raw audio uploads
resource "aws_s3_bucket" "input_audio" {
  bucket_prefix = "${var.project_name}-input-"
  force_destroy = true
}

# Processed MIDI outputs
resource "aws_s3_bucket" "output_midi" {
  bucket_prefix = "${var.project_name}-output-"
  force_destroy = true
}

# Block public access (Security Best Practice)
resource "aws_s3_bucket_public_access_block" "input_block" {
  bucket = aws_s3_bucket.input_audio.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "output_block" {
  bucket = aws_s3_bucket.output_midi.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Add lifecycle policy to delete files after 24 hours (Cost Optimization)
resource "aws_s3_bucket_lifecycle_configuration" "cleanup" {
  for_each = {
    input  = aws_s3_bucket.input_audio.id
    output = aws_s3_bucket.output_midi.id
  }
  bucket = each.value

  rule {
    id     = "expire-after-24h"
    status = "Enabled"

    expiration {
      days = 1
    }
  }
}

# --- 2. SQS Queues (Decoupled Pipeline) --- #

resource "aws_sqs_queue" "stem_jobs_dlq" {
  name = "${var.project_name}-stem-dlq"
}

resource "aws_sqs_queue" "stem_jobs" {
  name                       = "${var.project_name}-stem-jobs"
  visibility_timeout_seconds = 600 # 10 mins for heavy AI
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.stem_jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "midi_jobs_dlq" {
  name = "${var.project_name}-midi-dlq"
}

resource "aws_sqs_queue" "midi_jobs" {
  name                       = "${var.project_name}-midi-jobs"
  visibility_timeout_seconds = 300
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.midi_jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

# --- 3. DynamoDB Table --- #

resource "aws_dynamodb_table" "job_status" {
  name         = "${var.project_name}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# --- 4. IAM (Least Privilege) --- #

resource "aws_iam_role" "worker_role" {
  name = "${var.project_name}-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_policy" "worker_access" {
  name        = "${var.project_name}-worker-policy"
  description = "Minimalist policy for audio2midi workers"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = ["s3:GetObject", "s3:ListBucket", "s3:DeleteObject", "s3:PutObject"]
        Effect = "Allow"
        Resource = [
          aws_s3_bucket.input_audio.arn,
          "${aws_s3_bucket.input_audio.arn}/*",
          aws_s3_bucket.output_midi.arn,
          "${aws_s3_bucket.output_midi.arn}/*"
        ]
      },
      {
        Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:SendMessage", "sqs:GetQueueAttributes"]
        Effect = "Allow"
        Resource = [
          aws_sqs_queue.stem_jobs.arn,
          aws_sqs_queue.midi_jobs.arn
        ]
      },
      {
        Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Effect = "Allow"
        Resource = aws_dynamodb_table.job_status.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "worker_attach" {
  role       = aws_iam_role.worker_role.name
  policy_arn = aws_iam_policy.worker_access.arn
}

resource "aws_iam_role_policy_attachment" "worker_ssm_attach" {
  role       = aws_iam_role.worker_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "worker_profile" {
  name = "${var.project_name}-worker-profile"
  role = aws_iam_role.worker_role.name
}

# --- 5. Networking & Security --- #

resource "aws_security_group" "k3s_sg" {
  name        = "${var.project_name}-k3s-sg"
  description = "Security group for k3s cluster"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
    description = "Allow internal cluster communication"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- 6. EC2 Instance (Control Plane) --- #

data "aws_ami" "ubuntu_arm64" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
  }
}

data "aws_ami" "ubuntu_gpu" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*"]
  }
}

resource "random_password" "k3s_token" {
  length  = 32
  special = false
}

resource "aws_instance" "k3s_node" {
  ami                    = data.aws_ami.ubuntu_arm64.id
  instance_type          = "t4g.large"              # 8GB RAM Control Plane
  key_name               = "audio2midi-key"
  iam_instance_profile   = aws_iam_instance_profile.worker_profile.name
  vpc_security_group_ids = [aws_security_group.k3s_sg.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
              #!/bin/bash
              PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
              curl -sfL https://get.k3s.io | K3S_TOKEN=${random_password.k3s_token.result} INSTALL_K3S_EXEC="--tls-san $PUBLIC_IP" sh -
              export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
              chmod 644 /etc/rancher/k3s/k3s.yaml
              EOF

  tags = {
    Name = "${var.project_name}-node"
  }
}

# --- 7. Auto Scaling Group (Heavy AI Workers) --- #

resource "aws_launch_template" "worker_nodes" {
  name_prefix   = "${var.project_name}-worker-"
  image_id      = data.aws_ami.ubuntu_gpu.id
  instance_type = "g4dn.xlarge" # 16GB RAM NVIDIA T4 GPU
  key_name      = "audio2midi-key"

  iam_instance_profile {
    name = aws_iam_instance_profile.worker_profile.name
  }

  vpc_security_group_ids = [aws_security_group.k3s_sg.id]

  user_data = base64encode(<<-EOF
              #!/bin/bash
              curl -sfL https://get.k3s.io | K3S_URL=https://${aws_instance.k3s_node.private_ip}:6443 K3S_TOKEN=${random_password.k3s_token.result} sh -s - agent --node-label tier=worker
              EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.project_name}-asg-worker"
    }
  }
}

resource "aws_autoscaling_group" "ai_workers" {
  name                = "${var.project_name}-workers-asg"
  availability_zones  = [aws_instance.k3s_node.availability_zone]
  desired_capacity    = 0
  min_size            = 0
  max_size            = 5

  launch_template {
    id      = aws_launch_template.worker_nodes.id
    version = "$Latest"
  }
}

# --- 8. Auto Scaling Policies --- #

resource "aws_autoscaling_policy" "scale_out" {
  name                   = "sqs-scale-out"
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 120
  autoscaling_group_name = aws_autoscaling_group.ai_workers.name
}

resource "aws_autoscaling_policy" "scale_in" {
  name                   = "sqs-scale-in"
  scaling_adjustment     = -1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.ai_workers.name
}

resource "aws_cloudwatch_metric_alarm" "sqs_high" {
  alarm_name          = "${var.project_name}-queue-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = "60"
  statistic           = "Maximum"
  threshold           = "0"

  dimensions = {
    QueueName = aws_sqs_queue.stem_jobs.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_out.arn]
}

resource "aws_cloudwatch_metric_alarm" "sqs_low" {
  alarm_name          = "${var.project_name}-queue-low"
  comparison_operator = "LessThanOrEqualToThreshold"
  evaluation_periods  = "3"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = "60"
  statistic           = "Maximum"
  threshold           = "0"

  dimensions = {
    QueueName = aws_sqs_queue.stem_jobs.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_in.arn]
}
