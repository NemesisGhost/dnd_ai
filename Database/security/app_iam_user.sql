-- Ensure IAM-authenticated application user exists and has least-privilege access
-- This script is idempotent and safe to re-run.

-- 1) Create the role if it doesn't exist
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_iam_user') THEN
    CREATE ROLE "app_iam_user" LOGIN;
  END IF;
END
$$;

-- 2) Grant the AWS-managed rds_iam role to enable IAM token authentication
GRANT rds_iam TO "app_iam_user";

-- 3) Allow connecting to the database (explicit, in case CONNECT is restricted)
GRANT CONNECT ON DATABASE current_database() TO "app_iam_user";

-- 4) Minimal privileges for schema/table access (adjust as needed)
GRANT USAGE ON SCHEMA public TO "app_iam_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "app_iam_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "app_iam_user";

-- 5) Default privileges for future objects created by the role running migrations
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "app_iam_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "app_iam_user";

-- NOTE:
-- - If you use additional schemas, duplicate the GRANTs and DEFAULT PRIVILEGES per schema.
-- - If different owners create objects, ALTER DEFAULT PRIVILEGES must be executed by those owners as well.
