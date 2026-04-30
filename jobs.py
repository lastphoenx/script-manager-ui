#!/usr/bin/env python3
"""Job management: start, stop, monitor script executions."""

import os
import subprocess
import signal
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import yaml
import json

from config import settings
from models import JobModel

logger = logging.getLogger(__name__)


class ScriptDefinition:
    """Represents a script definition from scripts.yaml."""
    
    def __init__(self, data: Dict[str, Any]):
        self.name = data["name"]
        self.description = data.get("description", "")
        self.cmd = data["cmd"]
        self.args = data.get("args", [])
        self.cwd = Path(data.get("cwd", "."))
        self.category = data.get("category", "General")
        self.tags = data.get("tags", [])
        self.estimated_duration = data.get("estimated_duration", "unknown")
        self.risk_level = data.get("risk_level", "low")
        self.env_file = data.get("env_file")
        self.env = data.get("env", {})
        self.params = data.get("params", [])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "cmd": self.cmd,
            "args": self.args,
            "cwd": str(self.cwd),
            "category": self.category,
            "tags": self.tags,
            "estimated_duration": self.estimated_duration,
            "risk_level": self.risk_level,
            "env_file": self.env_file,
            "params": self.params,
        }


class ScriptRegistry:
    """Loads and manages script definitions."""
    
    def __init__(self, yaml_path: Path):
        self.yaml_path = yaml_path
        self.scripts: Dict[str, ScriptDefinition] = {}
        self.load()
    
    def load(self):
        """Load scripts from YAML file."""
        try:
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            self.scripts = {}
            for script_data in data.get("scripts", []):
                script = ScriptDefinition(script_data)
                self.scripts[script.name] = script
            
            logger.info(f"Loaded {len(self.scripts)} script definitions")
        except Exception as e:
            logger.error(f"Failed to load scripts.yaml: {e}")
            raise
    
    def get_script(self, name: str) -> Optional[ScriptDefinition]:
        """Get script definition by name."""
        return self.scripts.get(name)
    
    def list_scripts(self) -> List[ScriptDefinition]:
        """List all script definitions."""
        return list(self.scripts.values())


class JobManager:
    """Manages job execution lifecycle."""
    
    def __init__(self, registry: ScriptRegistry):
        self.registry = registry
        self.running_jobs: Dict[int, subprocess.Popen] = {}
    
    def start_job(
        self,
        job_id: int,
        script_name: str,
        parameters: Dict[str, Any],
    ) -> bool:
        """Start a job execution."""
        script = self.registry.get_script(script_name)
        if not script:
            logger.error(f"Script '{script_name}' not found")
            JobModel.update_job_status(
                job_id,
                status="failed",
                error_message=f"Script '{script_name}' not found"
            )
            return False
        
        try:
            # Build command with parameters
            cmd = self._build_command(script, parameters)
            
            # Prepare environment
            env = os.environ.copy()
            
            # Load env_file if specified (relative to script.cwd)
            if script.env_file:
                env_file_path = Path(script.cwd) / script.env_file
                if env_file_path.exists():
                    env_vars = self._load_env_file(str(env_file_path))
                    # Special handling for PATH/PYTHONPATH: append instead of replace
                    if 'PATH' in env_vars:
                        env_vars['PATH'] = f"{env_vars['PATH']}:{env.get('PATH', '')}"
                    if 'PYTHONPATH' in env_vars:
                        env_vars['PYTHONPATH'] = f"{env_vars['PYTHONPATH']}:{env.get('PYTHONPATH', '')}"
                    env.update(env_vars)
                else:
                    logger.warning(f"env_file not found: {env_file_path}")
            
            # Add inline env (also with PATH/PYTHONPATH append logic)
            script_env = script.env.copy()  # Create local copy to avoid mutating original
            if 'PATH' in script_env:
                script_env['PATH'] = f"{script_env['PATH']}:{env.get('PATH', '')}"
            if 'PYTHONPATH' in script_env:
                script_env['PYTHONPATH'] = f"{script_env['PYTHONPATH']}:{env.get('PYTHONPATH', '')}"
            env.update(script_env)
            
            # Create log file
            log_file = settings.LOGS_DIR / f"job_{job_id}.log"
            
            # Start process
            logger.info(f"Starting job {job_id}: {' '.join(cmd)} in {script.cwd}")
            
            # Write header to log file
            with open(log_file, "w", encoding="utf-8") as log_fp:
                log_fp.write(f"=== Job {job_id} started at {datetime.now().isoformat()} ===\n")
                log_fp.write(f"Script: {script_name}\n")
                log_fp.write(f"Command: {' '.join(cmd)}\n")
                log_fp.write(f"CWD: {script.cwd}\n")
                log_fp.write(f"Parameters: {json.dumps(parameters, indent=2)}\n")
                log_fp.write("=" * 70 + "\n\n")
            
            # Start process with separate file handle (stays open for subprocess)
            log_fp_proc = open(log_file, "a", encoding="utf-8", buffering=1)
            
            proc = subprocess.Popen(
                cmd,
                cwd=script.cwd,
                env=env,
                stdout=log_fp_proc,
                stderr=subprocess.STDOUT,
                text=True,
            )
            
            # Update job in database
            JobModel.update_job_status(
                job_id,
                status="running",
                pid=proc.pid,
                start_time=datetime.now(),
                log_file=str(log_file)
            )
            
            # Track running job
            self.running_jobs[job_id] = proc
            
            logger.info(f"Job {job_id} started with PID {proc.pid}")
            return True
            
        except Exception as e:
            logger.exception(f"Failed to start job {job_id}")
            JobModel.update_job_status(
                job_id,
                status="failed",
                error_message=str(e),
                end_time=datetime.now()
            )
            return False
    
    def check_job_status(self, job_id: int) -> Optional[str]:
        """Check if a running job has finished and update status."""
        if job_id not in self.running_jobs:
            return None
        
        proc = self.running_jobs[job_id]
        exit_code = proc.poll()
        
        if exit_code is not None:
            # Process finished
            status = "success" if exit_code == 0 else "failed"
            
            JobModel.update_job_status(
                job_id,
                status=status,
                exit_code=exit_code,
                end_time=datetime.now()
            )
            
            # Append completion to log
            job = JobModel.get_job(job_id)
            if job and job.get("log_file"):
                log_file = settings.BASE_DIR / job["log_file"]
                try:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"\n{'=' * 70}\n")
                        f.write(f"=== Job finished at {datetime.now().isoformat()} ===\n")
                        f.write(f"Exit code: {exit_code}\n")
                        f.write(f"Status: {status}\n")
                except Exception as e:
                    logger.error(f"Failed to append to log: {e}")
            
            # Remove from tracking
            del self.running_jobs[job_id]
            
            logger.info(f"Job {job_id} finished with exit code {exit_code} ({status})")
            return status
        
        return "running"
    
    def kill_job(self, job_id: int) -> bool:
        """Kill a running job."""
        if job_id not in self.running_jobs:
            logger.warning(f"Job {job_id} is not running")
            return False
        
        proc = self.running_jobs[job_id]
        
        try:
            # Try graceful termination first
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if still running
                proc.kill()
                proc.wait()
            
            JobModel.update_job_status(
                job_id,
                status="killed",
                end_time=datetime.now()
            )
            
            del self.running_jobs[job_id]
            logger.info(f"Job {job_id} killed")
            return True
            
        except Exception as e:
            logger.error(f"Failed to kill job {job_id}: {e}")
            return False
    
    def get_job_output(
        self,
        job_id: int,
        offset: int = 0,
        tail: Optional[int] = None
    ) -> Dict[str, Any]:
        """Read job output from log file."""
        job = JobModel.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        
        log_file = job.get("log_file")
        if not log_file:
            return {"output": "", "size": 0, "offset": 0}
        
        log_path = Path(log_file)
        
        if not log_path.exists():
            return {"output": "", "size": 0, "offset": 0}
        
        try:
            file_size = log_path.stat().st_size
            
            # Limit file size to prevent memory issues
            if file_size > settings.JOB_OUTPUT_MAX_SIZE:
                return {
                    "output": f"[Log file too large: {file_size} bytes]",
                    "size": file_size,
                    "offset": offset,
                    "truncated": True
                }
            
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                if tail:
                    # Read last N lines
                    lines = f.readlines()
                    output = "".join(lines[-tail:])
                else:
                    # Read from offset
                    f.seek(offset)
                    output = f.read()
            
            return {
                "output": output,
                "size": file_size,
                "offset": file_size,  # New offset for next read
                "truncated": False
            }
            
        except Exception as e:
            logger.error(f"Failed to read log file: {e}")
            return {"error": str(e)}
    
    def _build_command(
        self,
        script: ScriptDefinition,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Build command array from script definition and parameters."""
        cmd = [script.cmd] + script.args
        
        # Add parameters as command-line arguments
        for param_def in script.params:
            param_name = param_def["name"]
            param_type = param_def["type"]
            value = parameters.get(param_name)
            
            # Skip if not provided and not required
            if value is None:
                if param_def.get("required"):
                    raise ValueError(f"Required parameter '{param_name}' not provided")
                continue
            
            # Skip empty strings or False booleans
            if value == "" or (param_type == "bool" and not value):
                continue
            
            # Format based on type
            if param_type == "bool":
                # Boolean flags (only append if True)
                cmd.append(f"--{param_name}")
            else:
                # Convert underscores to hyphens for CLI compatibility (Python convention)
                cli_param = param_name.replace("_", "-")
                cmd.append(f"--{cli_param}")
                cmd.append(str(value))
        
        return cmd
    
    def _load_env_file(self, env_file: str) -> Dict[str, str]:
        """Load environment variables from .env file."""
        env = {}
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    if "=" in line:
                        key, value = line.split("=", 1)
                        env[key.strip()] = value.strip()
        except Exception as e:
            logger.warning(f"Failed to load env file {env_file}: {e}")
        
        return env


# Global instances
script_registry = ScriptRegistry(settings.SCRIPTS_YAML)
job_manager = JobManager(script_registry)
