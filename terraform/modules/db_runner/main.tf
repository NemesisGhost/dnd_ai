terraform {
  required_version = ">= 1.3.0"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
  keepers = {
    # Change this to force re-creation of the bucket if needed
    prefix = var.sql_prefix
  }
}

locals {
  # Base directory for the repo-level Database folder (three levels up from this module)
  database_dir  = abspath("${path.module}/../../../Database")
  sql_files     = fileset(local.database_dir, "**/*.sql")
  manifest_path = "${local.database_dir}/order.txt"
  manifest_hash = filesha1(local.manifest_path)
  sql_hash = sha1(join(
    "",
    concat(
      [local.manifest_hash],
      [for f in local.sql_files : filesha1("${local.database_dir}/${f}")]
    )
  ))
  sql_bucket_name = length(var.sql_bucket_name) > 0 ? var.sql_bucket_name : "db-runner-sql-${random_id.bucket_suffix.hex}"
  runner_name     = "db-runner-${substr(local.sql_hash, 0, 8)}"
}
