-- Run as a MySQL administrator (for example: mysql -u root -p < docs/mysql_setup.sql).
-- Replace the passwords before running. Never commit real passwords.
CREATE DATABASE IF NOT EXISTS ai_copilot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'app_user'@'localhost' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
GRANT ALL PRIVILEGES ON ai_copilot.* TO 'app_user'@'localhost';

-- Read-only account used by the NL-to-SQL agent. Created BEFORE or AFTER the tables exist;
-- it is granted SELECT on the business tables only (no users, documents, conversations, messages).
CREATE USER IF NOT EXISTS 'readonly_user'@'localhost' IDENTIFIED BY 'CHANGE_ME_READONLY_PASSWORD';
-- Run these GRANTs after `python scripts/init_database.py` has created the tables:
GRANT SELECT ON ai_copilot.customers   TO 'readonly_user'@'localhost';
GRANT SELECT ON ai_copilot.products    TO 'readonly_user'@'localhost';
GRANT SELECT ON ai_copilot.orders      TO 'readonly_user'@'localhost';
GRANT SELECT ON ai_copilot.order_items TO 'readonly_user'@'localhost';
GRANT SELECT ON ai_copilot.payments    TO 'readonly_user'@'localhost';
FLUSH PRIVILEGES;
