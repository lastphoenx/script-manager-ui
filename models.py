#!/usr/bin/env python3
"""Database models and interaction for Script Manager UI."""

import mysql.connector
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager
import logging

from config import settings

logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = None
    try:
        conn = mysql.connector.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASS,
            autocommit=False,
        )
        yield conn
    except mysql.connector.Error as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()


class JobModel:
    """Database operations for jobs."""
    
    @staticmethod
    def create_job(
        script_name: str,
        username: Optional[str],
        parameters: Dict[str, Any],
    ) -> int:
        """Create a new job entry and return its ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                # JSON serialization: cursor.execute handles quoting automatically
                params_json = json.dumps(parameters) if parameters else '{}'
                cursor.execute("""
                    INSERT INTO jobs (script_name, username, parameters, status)
                    VALUES (%s, %s, %s, 'pending')
                """, (script_name, username, params_json))
                conn.commit()
                job_id = cursor.lastrowid
                logger.info(f"Created job {job_id} for script '{script_name}' by user '{username}'")
                return job_id
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to create job: {e}")
                raise
            finally:
                cursor.close()
    
    @staticmethod
    def update_job_status(
        job_id: int,
        status: str,
        pid: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        exit_code: Optional[int] = None,
        log_file: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update job status and metadata."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                updates = ["status = %s"]
                params = [status]
                
                if pid is not None:
                    updates.append("pid = %s")
                    params.append(pid)
                
                if start_time is not None:
                    updates.append("start_time = %s")
                    params.append(start_time)
                
                if end_time is not None:
                    updates.append("end_time = %s")
                    params.append(end_time)
                
                if exit_code is not None:
                    updates.append("exit_code = %s")
                    params.append(exit_code)
                
                if log_file is not None:
                    updates.append("log_file = %s")
                    params.append(log_file)
                
                if error_message is not None:
                    updates.append("error_message = %s")
                    params.append(error_message)
                
                params.append(job_id)
                
                query = f"UPDATE jobs SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                logger.debug(f"Updated job {job_id} status to '{status}'")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to update job {job_id}: {e}")
                raise
            finally:
                cursor.close()
    
    @staticmethod
    def get_job(job_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single job by ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute("""
                    SELECT id, script_name, username, parameters, status, pid,
                           start_time, end_time, exit_code, log_file, error_message,
                           created_at, updated_at
                    FROM jobs
                    WHERE id = %s
                """, (job_id,))
                job = cursor.fetchone()
                return job
            finally:
                cursor.close()
    
    @staticmethod
    def list_jobs(
        limit: int = 100,
        script_name: Optional[str] = None,
        username: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                query = """
                    SELECT id, script_name, username, parameters, status, pid,
                           start_time, end_time, exit_code, log_file, error_message,
                           created_at, updated_at
                    FROM jobs
                    WHERE 1=1
                """
                params = []
                
                if script_name:
                    query += " AND script_name = %s"
                    params.append(script_name)
                
                if username:
                    query += " AND username = %s"
                    params.append(username)
                
                if status:
                    query += " AND status = %s"
                    params.append(status)
                
                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                
                cursor.execute(query, params)
                jobs = cursor.fetchall()
                return jobs
            finally:
                cursor.close()
    
    @staticmethod
    def delete_old_jobs(days: int = 30) -> int:
        """Delete jobs older than specified days. Returns count of deleted jobs."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    DELETE FROM jobs
                    WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
                    AND status IN ('success', 'failed', 'killed')
                """, (days,))
                conn.commit()
                deleted = cursor.rowcount
                logger.info(f"Deleted {deleted} old jobs (older than {days} days)")
                return deleted
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to delete old jobs: {e}")
                raise
            finally:
                cursor.close()


def ensure_db_schema():
    """Ensure database schema is created. Should be run on startup."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Test connection
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database schema check failed: {e}")
        logger.error("Please run init_db.sql to create the schema")
        raise
