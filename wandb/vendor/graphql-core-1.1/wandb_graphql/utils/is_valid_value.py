"""
    Implementation of isValidJSValue from graphql.s
"""

import collections
import json

from ..type import (GraphQLEnumType, GraphQLInputObjectType, GraphQLList,
                    GraphQLNonNull, GraphQLScalarType)

_empty_list = []


def is_valid_value(value, type):
    """Given a type and any value, return True if that value is valid."""
    if isinstance(type, GraphQLNonNull):
        of_type = type.of_type
        if value is None:
            return [f'Expected "{type}", found null.']

        return is_valid_value(value, of_type)

    if value is None:
        return _empty_list

    if isinstance(type, GraphQLList):
        item_type = type.of_type
        if not isinstance(value, str) and isinstance(value, collections.Iterable):
            errors = []
            for i, item in enumerate(value):
                item_errors = is_valid_value(item, item_type)
                for error in item_errors:
                    errors.append(f'In element #{i}: {error}')

            return errors

        else:
            return is_valid_value(value, item_type)

    if isinstance(type, GraphQLInputObjectType):
        if not isinstance(value, collections.Mapping):
            return [f'Expected "{type}", found not an object.']

        fields = type.fields
        errors = []

        for provided_field in sorted(value.keys()):
            if provided_field not in fields:
                errors.append(f'In field "{provided_field}": Unknown field.')

        for field_name, field in fields.items():
            subfield_errors = is_valid_value(value.get(field_name), field.type)
            errors.extend(f'In field "{field_name}": {e}' for e in subfield_errors)

        return errors

    assert isinstance(type, (GraphQLScalarType, GraphQLEnumType)), \
        'Must be input type'

    # Scalar/Enum input checks to ensure the type can parse the value to
    # a non-null value.
    parse_result = type.parse_value(value)
    if parse_result is None:
        return [f'Expected type "{type}", found {json.dumps(value)}.']

    return _empty_list
