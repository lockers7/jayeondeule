"""Relay and scheduler control module"""
from agri_ai_core.src.control.task_scheduler import (
    setup_scheduler,
    start_scheduler,
    stop_scheduler,
    add_job,
    setup_default_jobs,
)
from agri_ai_core.src.control.relay_manager import set_relay_value, get_relay_status
from agri_ai_core.src.control.schedule_control import control_all_schedules, control_lighting_schedule, control_irrigation_schedule
from agri_ai_core.src.control.manual_control import control_manual_environment, control_all_manual, control_all_ai
from agri_ai_core.src.control.ai_control import control_ai_environment

__all__ = [
    "setup_scheduler",
    "start_scheduler",
    "stop_scheduler",
    "add_job",
    "setup_default_jobs",
    "set_relay_value",
    "get_relay_status",
    "control_all_schedules",
    "control_lighting_schedule",
    "control_irrigation_schedule",
    "control_manual_environment",
    "control_all_manual",
    "control_all_ai",
    "control_ai_environment",
]
