output "input_bucket_name" {
  value = aws_s3_bucket.input_audio.id
}

output "output_bucket_name" {
  value = aws_s3_bucket.output_midi.id
}

output "dynamodb_table_name" {
  description = "The name of the DynamoDB table for job status"
  value       = aws_dynamodb_table.job_status.name
}

output "stem_repository_url" {
  description = "URL of the ECR repository for the Stem service"
  value       = aws_ecr_repository.stem_service.repository_url
}

output "midi_ecr_repository" {
  value = aws_ecr_repository.midi_service.repository_url
}

# output "stem_endpoint_name" {
#   value = aws_sagemaker_endpoint.stem_endpoint.name
# }

# output "midi_endpoint_name" {
#   value = aws_sagemaker_endpoint.midi_endpoint.name
# }

output "public_ip" {
  value = aws_instance.k3s_node.public_ip
}

output "cloudfront_url" {
  value = "https://${aws_cloudfront_distribution.web_distribution.domain_name}"
}

output "web_bucket_name" {
  value = aws_s3_bucket.web_client.id
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web_distribution.id
}
