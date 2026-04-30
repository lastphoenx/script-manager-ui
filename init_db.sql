-- Script Manager UI - MariaDB Schema
-- Database: script_manager

CREATE DATABASE IF NOT EXISTS script_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE script_manager;

-- Jobs table: tracks script executions
CREATE TABLE IF NOT EXISTS jobs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    script_name VARCHAR(255) NOT NULL,
    username VARCHAR(255) NULL COMMENT 'User from Authentik header',
    parameters JSON NULL COMMENT 'Script parameters as JSON',
    status ENUM('pending', 'running', 'success', 'failed', 'killed') NOT NULL DEFAULT 'pending',
    pid INT NULL COMMENT 'Process ID when running',
    start_time DATETIME NULL,
    end_time DATETIME NULL,
    exit_code INT NULL,
    log_file VARCHAR(512) NULL COMMENT 'Relative path to log file',
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_script_name (script_name),
    INDEX idx_username (username),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_start_time (start_time)
) ENGINE=InnoDB;

-- Script execution statistics (optional, for future analytics)
CREATE TABLE IF NOT EXISTS script_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    script_name VARCHAR(255) NOT NULL,
    total_runs INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    avg_duration_seconds DECIMAL(10, 2) NULL,
    last_run DATETIME NULL,
    
    UNIQUE KEY uniq_script (script_name)
) ENGINE=InnoDB;

-- User for the application (adjust password!)
-- CREATE USER IF NOT EXISTS 'script_manager'@'localhost' IDENTIFIED BY 'your_secure_password_here';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON script_manager.* TO 'script_manager'@'localhost';
-- FLUSH PRIVILEGES;
