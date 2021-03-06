"""Defines the results obtained after executing a job"""
from __future__ import unicode_literals

import json
import logging
from copy import deepcopy

import os

from data.data.value import FileValue, JsonValue
from data.data.json.data_v6 import convert_data_to_v6_json, DataV6
from job.configuration.data.data_file import DATA_FILE_STORE
from job.configuration.data.job_data import JobData
from job.seed.exceptions import InvalidSeedMetadataDefinition
from job.seed.metadata import METADATA_SUFFIX, SeedMetadata
from job.seed.results.outputs_json import SeedOutputsJson
from product.types import ProductFileMetadata

logger = logging.getLogger(__name__)


class JobResults(object):
    """Represents the results obtained after executing a job
    """

    def __init__(self, results_dict=None, do_validate=True):
        """Constructor

        :param results_dict: The dictionary representing the job results
        :type results_dict: dict
        """

        if not results_dict:
            results_dict = {}

        self._results_data = DataV6(results_dict, do_validate=True).get_data()

    @property
    def files(self):
        """Accessor for files in results"""
        return convert_data_to_v6_json(self._results_data).get_dict()['files']

    @property
    def json(self):
        """Accessor for json in results"""
        return convert_data_to_v6_json(self._results_data).get_dict()['json']

    def add_file_list_parameter(self, name, file_ids):
        """Adds a list of files to the job results

        :param name: The output parameter name
        :type name: string
        :param file_ids: The file IDs
        :type file_ids: [long]
        """

        self._results_data.add_value(FileValue(name, file_ids))

    def add_file_parameter(self, name, file_id):
        """Adds a file to the job results

        :param name: The output parameter name
        :type name: string
        :param file_id: The file ID
        :type file_id: long
        """

        self._results_data.add_value(FileValue(name, [file_id]))

    def add_output_to_data(self, output_name, job_data, input_name):
        """Adds the given output from the results as a new input in the given job data

        :param output_name: The name of the results output to add to the data
        :type output_name: string
        :param job_data: The job data
        :type job_data: :class:`job.configuration.data.job_data.JobData`
        :param input_name: The name of the data input
        :type input_name: string
        """

        output = self.files[output_name]
        if len(output) == 1:
            job_data.add_file_input(input_name, output[0])
        else:
            job_data.add_file_list_input(input_name, output)

    def add_output_json(self, output_name, value):
        """Adds the given output json from the seed.outputs.json file

        :param output_name: Output JSON key used to capture from output file
        :type output_name: str
        :param value: Raw value provided by job
        :type value: float or str or dict or array
        """

        self.json[output_name] = value

    def get_dict(self):
        """Returns the internal dictionary that represents these job results

        :returns: The dictionary representing the results
        :rtype: dict
        """

        return convert_data_to_v6_json(self._results_data).get_dict()

    def extend_interface_with_outputs_v5(self, interface, job_files):
        """Create an output_data like object for legacy v5 API

        :param interface: Seed manifest which should have concrete outputs injected
        :type interface: :class:`job.seed.manifest.SeedManifest`
        :param job_files: A list of files that are referenced by the job data.
        :type job_files: [:class:`storage.models.ScaleFile`]
        :return: A dictionary of Seed Manifest outputs key mapped to the corresponding data value.
        :rtype: dict
        """

        outputs = []
        output_files = deepcopy(interface.get_output_files())
        output_json = deepcopy(interface.get_output_json())

        file_map = {job_file.id: job_file for job_file in job_files}

        for i in output_files:
            try:
                i['value'] = [file_map[x] for x in self.files[i['name']]]
                if len(i['value']) >= 2:
                    i['type'] = 'files'
                else:
                    i['value'] = i['value'][0]
                    i['type'] = 'file'

                outputs.append(i)
            # Catch KeyError exceptions as a newly constructed JobResults object prior to execution will be missing keys
            except KeyError, ex:
                logger.debug(ex)

        for i in output_json:
            try:
                i['type'] = 'property'
                i['value'] = self.json[i['name']]
                outputs.append(i)
            # Catch KeyError exceptions as a newly constructed JobResults object prior to execution will be missing keys
            except KeyError, ex:
                logger.debug(ex)

        return outputs

    def perform_post_steps(self, job_interface, job_data, job_exe):
        """Stores the files or JSON output of job and deletes any working directories

        :param job_interface: The job interface
        :type job_interface: :class:`job.seed.manifest.SeedManifest`
        :param job_data: The job data
        :type job_data: :class:`job.data.job_data.JobData`
        :param job_exe: The job execution model with related job and job_type fields
        :type job_exe: :class:`job.models.JobExecution`
        :return: Job results generated by job execution
        :rtype: :class:`job.seed.results.job_results.JobResults`
        """

        # For compliance with Seed we must capture all files directly from the output directory.
        # The capture expressions can be found within `interface.outputs.files.pattern`

        output_files = self._capture_output_files(job_interface.get_seed_output_files())

        self._capture_output_json(job_interface.get_seed_output_json())

        self._store_output_data_files(output_files, job_data, job_exe)

    def _capture_output_files(self, seed_output_files):
        """Evaluate files patterns and capture any available side-car metadata associated with matched files

        :param seed_output_files: interface definition of Seed output files that should be captured
        :type seed_output_files: [`job.seed.types.SeedOutputFiles`]
        :return: collection of files name keys mapped to a ProductFileMetadata list. { name : [`ProductFileMetadata`]
        :rtype: dict
        """

        # Dict of detected files and associated metadata
        captured_files = {}

        # Iterate over each files object
        for output_file in seed_output_files:
            # For files obj that are detected, handle results (may be multiple)
            product_files = []
            for matched_file in output_file.get_files():
                logger.info('File detected for output capture: %s' % matched_file)

                product_file_meta = ProductFileMetadata(output_file.name, matched_file, output_file.media_type)

                # check to see if there is a side-car metadata file
                metadata_file = matched_file + METADATA_SUFFIX

                # If metadata is found, attempt to grab any Scale relevant data and place in ProductFileMetadata tuple
                if os.path.isfile(metadata_file):
                    logger.info('Capturing metadata from detected side-car file: %s' % metadata_file)
                    with open(metadata_file) as metadata_file_handle:
                        try:
                            metadata = SeedMetadata.metadata_from_json(json.load(metadata_file_handle))

                            # Property keys per #1160
                            product_file_meta.geojson = metadata.data
                            product_file_meta.data_start = metadata.get_property('dataStarted')
                            product_file_meta.data_end = metadata.get_property('dataEnded')

                            product_file_meta.source_started = metadata.get_property('sourceStarted')
                            product_file_meta.source_ended = metadata.get_property('sourceEnded')
                            product_file_meta.source_sensor_class = metadata.get_property('sourceSensorClass')
                            product_file_meta.source_sensor = metadata.get_property('sourceSensor')
                            product_file_meta.source_collection = metadata.get_property('sourceCollection')
                            product_file_meta.source_task = metadata.get_property('sourceTask')
                        except InvalidSeedMetadataDefinition:
                            logger.exception()

                product_files.append(product_file_meta)

            captured_files[output_file.name] = product_files

        return captured_files

    def _capture_output_json(self, output_json_interface):
        """Captures any JSON property output from a job execution

        :param outputs_json_interface: List of output json interface objects
        :type outputs_json_interface: [:class:`job.seed.types.SeedOutputJson`]
        """

        # Identify any outputs from seed.outputs.json
        try:
            schema = SeedOutputsJson.construct_schema(output_json_interface)
            outputs = SeedOutputsJson.read_outputs(schema)
            seed_outputs_json = outputs.get_values(output_json_interface)

            for key in seed_outputs_json:
                self.add_output_json(key, seed_outputs_json[key])
        except IOError:
            logger.warning('No seed.outputs.json file found to process.')

    def _store_output_data_files(self, data_files, job_data, job_exe):
        """Stores the given output data

        :param data_files: Dict with each file parameter name mapping to a ProductFileMetadata class
        :type data_files: {string: ProductFileMetadata)
        :param job_exe: The job execution model (with related job and job_type fields) that is storing the output data
            files
        :type job_exe: :class:`job.models.JobExecution`
        :returns: The job results
        :rtype: :class:`job.seed.results.job_results.JobResults`
        """

        # Organize the data files
        workspace_files = {}  # Workspace ID -> [`ProductFileMetadata`]
        params_by_file_path = {}  # Absolute local file path -> output parameter name
        output_workspaces = JobData.create_output_workspace_dict(data_files.keys(), job_data, job_exe)
        for name in data_files:
            workspace_id = output_workspaces[name]
            if workspace_id in workspace_files:
                workspace_file_list = workspace_files[workspace_id]
            else:
                workspace_file_list = []
                workspace_files[workspace_id] = workspace_file_list
            data_file_entry = data_files[name]
            for entry in data_file_entry:
                file_path = os.path.normpath(entry.local_path)
                if not os.path.isfile(file_path):
                    raise Exception('%s is not a valid file' % file_path)
                params_by_file_path[file_path] = name
                workspace_file_list.append(entry)

        data_file_store = DATA_FILE_STORE['DATA_FILE_STORE']
        if not data_file_store:
            raise Exception('No data file store found')
        stored_files = data_file_store.store_files(workspace_files, job_data.get_input_file_ids(), job_exe)

        # Organize results
        param_file_ids = {}  # Output parameter name -> file ID or [file IDs]
        for file_path in stored_files:
            file_id = stored_files[file_path]
            name = params_by_file_path[file_path]
            if name in param_file_ids:
                file_id_list = param_file_ids[name]
            else:
                file_id_list = []
                param_file_ids[name] = file_id_list
            file_id_list.append(file_id)

        # Create job results
        for name in param_file_ids:
            param_entry = param_file_ids[name]
            self.add_file_list_parameter(name, param_entry)

        return self
