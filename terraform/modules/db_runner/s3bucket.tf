resource "aws_s3_bucket_server_side_encryption_configuration" "sql_bucket_sse" {
  bucket = aws_s3_bucket.sql_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "sql_bucket_versioning" {
  bucket = aws_s3_bucket.sql_bucket.id

  versioning_configuration {
    status     = "Enabled"   # or "Suspended"
    mfa_delete = "Disabled"  # optional; "Enabled" requires bucket-level MFA delete
  }
}

resource "aws_s3_bucket" "sql_bucket" {
  bucket = local.sql_bucket_name

  # Set force_destroy to true in dev/test so the bucket can be destroyed even if it contains objects.
  # Omit or set to false in prod to prevent accidental data loss.
  force_destroy = true

  tags = {
    Name = local.sql_bucket_name
    Role = "db-runner"
  }
}