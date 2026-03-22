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

# --- 2. ECR Repositories (For SageMaker Containers) --- #

resource "aws_ecr_repository" "stem_service" {
  name                 = "${var.project_name}-stem-service"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecr_repository" "midi_service" {
  name                 = "${var.project_name}-midi-service"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
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

# --- 4. IAM (Client API and SageMaker Execution) --- #

resource "aws_iam_role" "api_role" {
  name = "${var.project_name}-api-role"

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

resource "aws_iam_policy" "api_access" {
  name        = "${var.project_name}-api-policy"
  description = "Allows API to hit SageMaker endpoints and DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = ["s3:GetObject", "s3:PutObject"]
        Effect = "Allow"
        Resource = [
          aws_s3_bucket.input_audio.arn,
          "${aws_s3_bucket.input_audio.arn}/*"
        ]
      },
      {
        Action   = ["sagemaker:InvokeEndpointAsync"]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Effect = "Allow"
        Resource = aws_dynamodb_table.job_status.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_attach" {
  role       = aws_iam_role.api_role.name
  policy_arn = aws_iam_policy.api_access.arn
}

resource "aws_iam_role_policy_attachment" "api_ssm_attach" {
  role       = aws_iam_role.api_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "api_profile" {
  name = "${var.project_name}-api-profile"
  role = aws_iam_role.api_role.name
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
  instance_type          = "t4g.large" # 8GB RAM Control Plane
  key_name               = "audio2midi-key"
  iam_instance_profile   = aws_iam_instance_profile.api_profile.name
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

# --- 5. SageMaker IAM Execution Role --- #

resource "aws_iam_role" "sagemaker_execution_role" {
  name = "${var.project_name}-sagemaker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "sagemaker.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_policy" "sagemaker_s3_policy" {
  name        = "${var.project_name}-sm-policy"
  description = "Allows SageMaker to read inputs and write outputs seamlessly to S3 and DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Effect = "Allow"
        Resource = [
          aws_s3_bucket.input_audio.arn,
          "${aws_s3_bucket.input_audio.arn}/*",
          aws_s3_bucket.output_midi.arn,
          "${aws_s3_bucket.output_midi.arn}/*"
        ]
      },
      {
        Action   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:log-group:/aws/sagemaker/*"
      },
      {
        Action = ["dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:GetItem"]
        Effect = "Allow"
        Resource = aws_dynamodb_table.job_status.arn
      },
      {
        Action = ["sagemaker:InvokeEndpointAsync"]
        Effect = "Allow"
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sm_attach" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = aws_iam_policy.sagemaker_s3_policy.arn
}

# --- 6. SageMaker Endpoints (GPU Serverless) --- #

resource "aws_sagemaker_model" "stem_model" {
  name               = "${var.project_name}-stem-model"
  execution_role_arn = aws_iam_role.sagemaker_execution_role.arn
  primary_container {
    image = "${aws_ecr_repository.stem_service.repository_url}:latest"
    environment = {
      S3_OUTPUT_BUCKET = aws_s3_bucket.output_midi.bucket
      MIDI_ENDPOINT_NAME = "${var.project_name}-midi-endpoint"
      DYNAMODB_TABLE = aws_dynamodb_table.job_status.name
    }
  }
}

resource "aws_sagemaker_model" "midi_model" {
  name               = "${var.project_name}-midi-model"
  execution_role_arn = aws_iam_role.sagemaker_execution_role.arn
  primary_container {
    image = "${aws_ecr_repository.midi_service.repository_url}:latest"
    environment = {
      S3_OUTPUT_BUCKET = aws_s3_bucket.output_midi.bucket
      DYNAMODB_TABLE = aws_dynamodb_table.job_status.name
    }
  }
}

resource "aws_sagemaker_endpoint_configuration" "stem_config" {
  name = "${var.project_name}-stem-config"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.stem_model.name
    initial_instance_count = 1
    instance_type          = "ml.g4dn.xlarge"
  }

  async_inference_config {
    output_config {
      s3_output_path = "s3://${aws_s3_bucket.output_midi.bucket}/stems/"
    }
  }
}

resource "aws_sagemaker_endpoint_configuration" "midi_config" {
  name = "${var.project_name}-midi-config"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.midi_model.name
    initial_instance_count = 1
    instance_type          = "ml.g4dn.xlarge"
  }

  async_inference_config {
    output_config {
      s3_output_path = "s3://${aws_s3_bucket.output_midi.bucket}/midi/"
    }
  }
}

resource "aws_sagemaker_endpoint" "stem_endpoint" {
  name                 = "${var.project_name}-stem-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.stem_config.name
}

resource "aws_sagemaker_endpoint" "midi_endpoint" {
  name                 = "${var.project_name}-midi-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.midi_config.name
}

# Auto-Scale endpoints to 0
resource "aws_appautoscaling_target" "stem_target" {
  max_capacity       = 1
  min_capacity       = 0
  resource_id        = "endpoint/${aws_sagemaker_endpoint.stem_endpoint.name}/variant/AllTraffic"
  scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
  service_namespace  = "sagemaker"
}

resource "aws_appautoscaling_target" "midi_target" {
  max_capacity       = 1
  min_capacity       = 0
  resource_id        = "endpoint/${aws_sagemaker_endpoint.midi_endpoint.name}/variant/AllTraffic"
  scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
  service_namespace  = "sagemaker"
}

resource "aws_appautoscaling_policy" "stem_scale" {
  name               = "stem-scale-policy"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.stem_target.resource_id
  scalable_dimension = aws_appautoscaling_target.stem_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.stem_target.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 1.0
    customized_metric_specification {
      metric_name = "ApproximateBacklogSizePerInstance"
      namespace   = "AWS/SageMaker"
      statistic   = "Average"
      dimensions {
        name  = "EndpointName"
        value = aws_sagemaker_endpoint.stem_endpoint.name
      }
    }
  }
}
