"""Defines the class that represents running job executions"""
from __future__ import unicode_literals

import logging
import threading
from datetime import datetime, timedelta

from django.db import transaction

from error.models import Error
from job.execution.running.tasks.factory import TaskFactory
from job.models import JobExecution


logger = logging.getLogger(__name__)


class RunningJobExecution(object):
    """This class represents a currently running job execution. This class is thread-safe."""

    def __init__(self, job_exe, task_factory=None):
        """Constructor

        :param job_exe: The job execution, which must be in RUNNING status and have its related node, job, job_type and
            job_type_rev models populated
        :type job_exe: :class:`job.models.JobExecution`
        :param task_factory: The factory to use for creating the job execution tasks
        :type task_factory: :class:`job.execution.running.tasks.factory.TaskFactory`
        """

        self._id = job_exe.id
        self._job_type_id = job_exe.job.job_type_id
        self._node_id = job_exe.node.id

        self._lock = threading.Lock()
        self._current_task = None
        self._remaining_tasks = []

        # Create tasks
        if not task_factory:
            task_factory = TaskFactory()
        if not job_exe.is_system:
            pre_task = task_factory.create_pre_task(job_exe)
            self._remaining_tasks.append(pre_task.get_id())
        job_task = task_factory.create_job_task(job_exe)
        self._remaining_tasks.append(job_task.get_id())
        if not job_exe.is_system:
            post_task = task_factory.create_post_task(job_exe)
            self._remaining_tasks.append(post_task.get_id())

    @property
    def current_task(self):
        """Returns the currently running task of the job execution, or None if no task is currently running

        :returns: The current task, possibly None
        :rtype: :class:`job.execution.running.tasks.base_task.Task`
        """

        with self._lock:
            return self._current_task

    @property
    def id(self):
        """Returns the ID of this job execution

        :returns: The ID of the job execution
        :rtype: int
        """

        return self._id

    @property
    def job_type_id(self):
        """Returns the job type ID of this job execution

        :returns: The job type ID of the job execution
        :rtype: int
        """

        return self._job_type_id

    @property
    def node_id(self):
        """Returns the ID of this job execution's node

        :returns: The ID of the node
        :rtype: int
        """

        return self._node_id

    def execution_canceled(self):
        """Cancels this job execution and returns the current task

        :returns: The current task, possibly None
        :rtype: :class:`job.execution.running.tasks.base_task.Task`
        """

        with self._lock:
            task = self._current_task
            self._current_task = None
            self._remaining_tasks = []
            return task

    def execution_lost(self, when):
        """Fails this job execution for its node becoming lost and returns the current task

        :param when: The time that the node was lost
        :type when: :class:`datetime.datetime`
        :returns: The current task, possibly None
        :rtype: :class:`job.execution.running.tasks.base_task.Task`
        """

        with self._lock:
            # TODO: move error into job app
            from scheduler.scheduler_errors import get_node_lost_error
            error = get_node_lost_error()
            from queue.models import Queue
            Queue.objects.handle_job_failure(self._id, when, error)

            task = self._current_task
            self._current_task = None
            self._remaining_tasks = []
            return task

    def execution_timed_out(self, when):
        """Fails this job execution for timing out and returns the current task

        :param when: The time that the job execution timed out
        :type when: :class:`datetime.datetime`
        :returns: The current task, possibly None
        :rtype: :class:`job.execution.running.tasks.base_task.Task`
        """

        with self._lock:
            # TODO: move error into job app
            from scheduler.scheduler_errors import get_timeout_error
            error = get_timeout_error()
            from queue.models import Queue
            Queue.objects.handle_job_failure(self._id, when, error)

            task = self._current_task
            self._current_task = None
            self._remaining_tasks = []
            return task

    def is_finished(self):
        """Indicates whether this job execution is finished with all tasks

        :returns: True if all tasks are finished, False otherwise
        :rtype: bool
        """

        with self._lock:
            return not self._current_task and not self._remaining_tasks

    def is_next_task_ready(self):
        """Indicates whether the next task in this job execution is ready

        :returns: True if the next task is ready, False otherwise
        :rtype: bool
        """

        with self._lock:
            return not self._current_task and self._remaining_tasks

    def next_task_resources(self):
        """Returns the resources that are required by the next task in this job execution. Returns None if there are no
        remaining tasks.

        :returns: The resources required by the next task, possibly None
        :rtype: :class:`job.resources.NodeResources`
        """

        with self._lock:
            if not self._remaining_tasks:
                return None

            next_task = self._remaining_tasks[0]
            return next_task.get_resources()

    def start_next_task(self):
        """Starts the next task in the job execution and returns it. Returns None if the next task is not ready or no
        tasks remain.

        :returns: The new task that was started, possibly None
        :rtype: :class:`job.execution.running.tasks.base_task.Task`
        """

        with self._lock:
            if self._current_task or not self._remaining_tasks:
                return None

            self._current_task = self._remaining_tasks.pop(0)
            return self._current_task

    def task_complete(self, task_results):
        """Completes a task for this job execution

        :param task_results: The task results
        :type task_results: :class:`job.execution.running.tasks.results.TaskResults`
        """

        with self._lock:
            if not self._current_task or self._current_task.id != task_results.task_id:
                return

            with transaction.atomic():
                self._current_task.complete(task_results)
                if not self._remaining_tasks:
                    from queue.models import Queue
                    Queue.objects.handle_job_completion(self._id, task_results.when)

            self._current_task = None

    def task_fail(self, task_results, error=None):
        """Fails a task for this job execution

        :param task_results: The task results
        :type task_results: :class:`job.execution.running.tasks.results.TaskResults`
        :param error: The error that caused this task to fail, possibly None
        :type error: :class:`error.models.Error`
        """

        with self._lock:
            if not self._current_task or self._current_task.id != task_results.task_id:
                return

            with transaction.atomic():
                error = self._current_task.fail(task_results, error)
                if not error:
                    # TODO: clean this up
                    error = Error.objects.get_unknown_error()
                from queue.models import Queue
                Queue.objects.handle_job_failure(self._id, task_results.when, error)

                # TODO: move this somewhere else and refactor it
                from scheduler.models import Scheduler
                job_exe = JobExecution.objects.get_job_exe_with_job_and_job_type(self._id)
                node = job_exe.node
                # Check for a high number of system errors and decide if we should pause the node
                if error.category == 'SYSTEM' and job_exe.job.num_exes >= job_exe.job.max_tries and node is not None and not node.is_paused:
                    # search Job.objects. for the number of system failures in the past (configurable) 1 minute
                    # if (configurable) 5 or more have occurred, pause the node
                    node_error_period = Scheduler.objects.first().node_error_period
                    if node_error_period > 0:
                        check_time = datetime.utcnow() - timedelta(minutes=node_error_period)
                        # find out how many jobs have recently failed on this node with a system error
                        num_node_errors = JobExecution.objects.select_related('error', 'node').filter(
                            status='FAILED', error__category='SYSTEM', ended__gte=check_time, node=node).distinct('job').count()
                        max_node_errors = Scheduler.objects.first().max_node_errors
                        if num_node_errors >= max_node_errors:
                            logger.warning('%s failed %d jobs in %d minutes, pausing the host' % (node.hostname, num_node_errors, node_error_period))
                            with transaction.atomic():
                                node.is_paused = True
                                node.is_paused_errors = True
                                node.pause_reason = "System Failure Rate Too High"
                                node.save()

            self._current_task = None
            self._remaining_tasks = []

    def task_running(self, task_id, when, stdout_url, stderr_url):
        """Tells this job execution that one of its tasks has started running

        :param task_id: The ID of the task
        :type task_id: str
        :param when: The time that the task started running
        :type when: :class:`datetime.datetime`
        :param stdout_url: The URL for the task's stdout logs
        :type stdout_url: str
        :param stderr_url: The URL for the task's stderr logs
        :type stderr_url: str
        """

        with self._lock:
            if not self._current_task or self._current_task.id != task_id:
                return

            self._current_task.running(when, stdout_url, stderr_url)
