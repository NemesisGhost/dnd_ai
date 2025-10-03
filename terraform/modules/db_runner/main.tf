terraform {
  required_version = ">= 1.3.0"
}

locals {
    name = "db-runner"

    sql_dir = "${path.module}/../../Database/"
    sql_files = fileset(local.sql_dir, "**/*.sql")

    sql_file_hashes = [
    for f in local.sql_files :
    filesha1("${local.sql_dir}/${f}")
    ]
    combined_sql_hash = sha1(join("", local.sql_file_hashes))
}