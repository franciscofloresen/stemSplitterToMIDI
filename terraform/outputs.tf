output "input_bucket_name" {
  value = aws_s3_bucket.input_audio.id
}

output "output_bucket_name" {
  value = aws_s3_bucket.output_midi.id
}

output "stem_queue_url" {
  value = aws_sqs_queue.stem_jobs.id
}

output "midi_queue_url" {
  value = aws_sqs_queue.midi_jobs.id
}

output "dynamodb_table" {
  value = aws_dynamodb_table.job_status.name
}

output "public_ip" {
  value = aws_instance.k3s_node.public_ip
}

output "cloudfront_url" {
  value = "https://${aws_cloudfront_distribution.web_distribution.domain_name}"
}
