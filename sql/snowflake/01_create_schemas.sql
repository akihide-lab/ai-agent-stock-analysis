-- Snowflake schemas for the optional analysis DWH.
-- Run with a role that has the minimum required CREATE SCHEMA privileges.

CREATE SCHEMA IF NOT EXISTS RAW;
CREATE SCHEMA IF NOT EXISTS CLEAN;
CREATE SCHEMA IF NOT EXISTS MART;
