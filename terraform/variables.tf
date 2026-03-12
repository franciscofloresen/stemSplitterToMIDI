variable "aws_region" {
  description = "AWS region for infrastructure"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name to prefix resources"
  type        = string
  default     = "audio2midi"
}

variable "allowed_cidr" {
  description = "CIDR block allowed to access SSH and K8s API (set to your IP/32 for security)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "alarm_email" {
  description = "Email address for CloudWatch billing and error alerts"
  type        = string
  default     = "franciscofloresenr@gmail.com"
}

variable "billing_threshold" {
  description = "The dollar amount for the monthly billing alarm threshold"
  type        = string
  default     = "40"
}
