"""Defines a command message that purges a source file"""
from __future__ import unicode_literals

import logging

from django.utils import timezone

from ingest.models import Ingest
from job.models import JobInputFile
from messaging.messages.message import CommandMessage
from recipe.models import RecipeInputFile
from storage.models import PurgeResults, ScaleFile


logger = logging.getLogger(__name__)


def create_purge_source_file_message(source_file_id, trigger_id):
    """Creates messages to removes a source file form Scale

    :param source_file_id: The source file ID
    :type source_file_id: int
    :param trigger_id: The trigger event ID for the purge operation
    :type trigger_id: int
    :return: The purge source file message
    :rtype: :class:`storage.messages.purge_source_file.PurgeSourceFile`
    """

    message = PurgeSourceFile()
    message.source_file_id = source_file_id
    message.trigger_id = trigger_id

    return message


class PurgeSourceFile(CommandMessage):
    """Command message that removes source file models
    """

    def __init__(self):
        """Constructor
        """

        super(PurgeSourceFile, self).__init__('purge_source_file')

        self.source_file_id = None
        self.trigger_id = None


    def to_json(self):
        """See :meth:`messaging.messages.message.CommandMessage.to_json`
        """

        return {'source_file_id': self.source_file_id, 'trigger_id': self.trigger_id}

    @staticmethod
    def from_json(json_dict):
        """See :meth:`messaging.messages.message.CommandMessage.from_json`
        """

        message = PurgeSourceFile()
        message.source_file_id = json_dict['source_file_id']
        message.trigger_id = json_dict['trigger_id']

        return message

    def execute(self):
        """See :meth:`messaging.messages.message.CommandMessage.execute`
        """

        # Check to see if a force stop was placed on this purge process
        results = PurgeResults.objects.get(source_file_id=self.source_file_id)
        if results.force_stop_purge:
            return True

        job_inputs = JobInputFile.objects.filter(input_file=self.source_file_id,
                                                 job__recipe__isnull=True).select_related('job')
        recipe_inputs = RecipeInputFile.objects.filter(input_file=self.source_file_id,
                                                       recipe__is_superseded=False).select_related('recipe')

        # Kick off spawn_delete_job_files for jobs that are not in a recipe and have the given source_file as input
        for job_input in job_inputs:
            from job.messages.spawn_delete_files_job import create_spawn_delete_files_job
            self.new_messages.append(create_spawn_delete_files_job(job_id=job_input.job.id,
                                                                   trigger_id=self.trigger_id,
                                                                   source_file_id=self.source_file_id,
                                                                   purge=True))

        # Kick off purge_recipe for recipes that are not superseded and have the given source_file as input
        for recipe_input in recipe_inputs:
            from recipe.messages.purge_recipe import create_purge_recipe_message
            self.new_messages.append(create_purge_recipe_message(recipe_id=recipe_input.recipe.id,
                                                                 trigger_id=self.trigger_id,
                                                                 source_file_id=self.source_file_id))

        # Delete Ingest and ScaleFile
        if not job_inputs and not recipe_inputs:
            Ingest.objects.filter(source_file=self.source_file_id).delete()
            ScaleFile.objects.filter(id=self.source_file_id).delete()
            PurgeResults.objects.filter(source_file_id=self.source_file_id).update(
                purge_completed=timezone.now())

        return True
