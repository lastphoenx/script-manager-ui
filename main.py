#!/usr/bin/env python3
"""Script Manager UI - FastAPI Backend."""

import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from models import JobModel, ensure_db_schema
from jobs import script_registry, job_manager

# Setup logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# === Lifespan Management ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    logger.info("Starting Script Manager UI")
    
    # Ensure database schema exists
    try:
        ensure_db_schema()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.error("Please run init_db.sql to create the schema")
    
    # Start background job monitor
    monitor_task = asyncio.create_task(background_job_monitor())
    
    logger.info("Script Manager UI started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Script Manager UI")
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


# FastAPI app
app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description="Web UI for managing and executing scripts",
    lifespan=lifespan
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Request/Response Models ===

class JobStartRequest(BaseModel):
    """Request body for starting a job."""
    script_name: str = Field(..., description="Name of the script to run")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Script parameters")


class JobResponse(BaseModel):
    """Response model for job information."""
    id: int
    script_name: str
    username: Optional[str]
    parameters: Dict[str, Any]
    status: str
    pid: Optional[int]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    exit_code: Optional[int]
    log_file: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class JobOutputResponse(BaseModel):
    """Response model for job output."""
    output: str
    size: int
    offset: int
    truncated: bool = False


# === Helper Functions ===

def get_username_from_header(request: Request) -> Optional[str]:
    """Extract username from Authentik forward auth header."""
    if not settings.AUTH_REQUIRED:
        return "anonymous"
    
    username = request.headers.get(settings.AUTHENTIK_HEADER)
    
    if not username and settings.AUTH_REQUIRED:
        logger.warning(f"Missing {settings.AUTHENTIK_HEADER} header")
    
    return username or "unknown"


async def background_job_monitor():
    """Background task to monitor running jobs."""
    while True:
        try:
            # Check all running jobs
            for job_id in list(job_manager.running_jobs.keys()):
                job_manager.check_job_status(job_id)
            
            await asyncio.sleep(2)  # Check every 2 seconds
        except Exception as e:
            logger.error(f"Background monitor error: {e}")
            await asyncio.sleep(5)


# === API Endpoints ===

@app.get("/")
async def root():
    """Serve the main UI."""
    return FileResponse("static/index.html")


@app.get("/api/scripts", response_model=List[Dict[str, Any]])
async def list_scripts():
    """List all available scripts."""
    scripts = script_registry.list_scripts()
    return [script.to_dict() for script in scripts]


@app.get("/api/scripts/{script_name}", response_model=Dict[str, Any])
async def get_script(script_name: str):
    """Get details of a specific script."""
    script = script_registry.get_script(script_name)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script.to_dict()


@app.post("/api/jobs", response_model=Dict[str, Any])
async def start_job(
    request: Request,
    job_request: JobStartRequest,
    background_tasks: BackgroundTasks,
):
    """Start a new job."""
    username = get_username_from_header(request)
    
    # Validate script exists
    script = script_registry.get_script(job_request.script_name)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    
    # Create job in database
    try:
        job_id = JobModel.create_job(
            script_name=job_request.script_name,
            username=username,
            parameters=job_request.parameters,
        )
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail="Failed to create job")
    
    # Start job execution in background
    success = job_manager.start_job(
        job_id=job_id,
        script_name=job_request.script_name,
        parameters=job_request.parameters,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start job")
    
    job = JobModel.get_job(job_id)
    return {
        "message": "Job started successfully",
        "job": job
    }


@app.get("/api/jobs", response_model=List[Dict[str, Any]])
async def list_jobs(
    limit: int = 100,
    script_name: Optional[str] = None,
    username: Optional[str] = None,
    status: Optional[str] = None,
):
    """List jobs with optional filters."""
    try:
        jobs = JobModel.list_jobs(
            limit=limit,
            script_name=script_name,
            username=username,
            status=status,
        )
        return jobs
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail="Failed to list jobs")


@app.get("/api/jobs/{job_id}", response_model=Dict[str, Any])
async def get_job(job_id: int):
    """Get details of a specific job."""
    # Check if job is running and update status
    job_manager.check_job_status(job_id)
    
    job = JobModel.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/output")
async def get_job_output(
    job_id: int,
    offset: int = 0,
    tail: Optional[int] = None,
):
    """Get job output (log file content)."""
    result = job_manager.get_job_output(job_id, offset=offset, tail=tail)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result


@app.post("/api/jobs/{job_id}/kill")
async def kill_job(job_id: int, request: Request):
    """Kill a running job."""
    username = get_username_from_header(request)
    
    job = JobModel.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail="Job is not running")
    
    success = job_manager.kill_job(job_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to kill job")
    
    logger.info(f"Job {job_id} killed by user {username}")
    
    return {
        "message": "Job killed successfully",
        "job_id": job_id
    }


@app.get("/api/stats")
async def get_stats():
    """Get system statistics."""
    try:
        all_jobs = JobModel.list_jobs(limit=1000)
        
        stats = {
            "total_jobs": len(all_jobs),
            "running_jobs": len([j for j in all_jobs if j["status"] == "running"]),
            "pending_jobs": len([j for j in all_jobs if j["status"] == "pending"]),
            "success_jobs": len([j for j in all_jobs if j["status"] == "success"]),
            "failed_jobs": len([j for j in all_jobs if j["status"] == "failed"]),
            "total_scripts": len(script_registry.list_scripts()),
        }
        
        return stats
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": settings.APP_VERSION,
    }


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
