"""Defines exceptions that can occur when interacting with batch definitions"""
from util.exceptions import ValidationException


class InvalidDefinition(ValidationException):
    """Exception indicating that the provided batch definition was invalid"""

    def __init__(self, name, description):
        """Constructor

        :param name: The name of the validation error
        :type name: string
        :param description: The description of the validation error
        :type description: string
        """

        super(InvalidDefinition, self).__init__(name, description)
