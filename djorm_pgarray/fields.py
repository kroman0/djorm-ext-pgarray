# -*- coding: utf-8 -*-

import json

import django
from django import forms
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import six
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _


TYPES = {
    'int': int,
    'smallint': int,
    'bigint': int,
    'text': str,
    'double precision': float,
    'varchar': str,
    'date': lambda x: x,
    'datetime': lambda x: x,
}


def _cast_to_unicode(data):
    if isinstance(data, (list, tuple)):
        return [_cast_to_unicode(x) for x in data]
    elif isinstance(data, str):
        return force_text(data)
    return data


def _cast_to_type(data, type_cast):
    if isinstance(data, (list, tuple)):
        return [_cast_to_type(x, type_cast) for x in data]
    if type_cast == str:
        return force_text(data)
    return type_cast(data)


def _unserialize(value):
    if not isinstance(value, six.string_types):
        return _cast_to_unicode(value)
    try:
        return _cast_to_unicode(json.loads(value))
    except ValueError:
        return _cast_to_unicode(value)


class ArrayField(six.with_metaclass(models.SubfieldBase, models.Field)):
    def __init__(self, *args, **kwargs):
        self._array_type = kwargs.pop('dbtype', 'int')
        type_key = self._array_type.split('(')[0]

        if "type_cast" in kwargs:
            self._type_cast = kwargs.pop("type_cast")
        elif type_key in TYPES:
            self._type_cast = TYPES[type_key]
        else:
            self._type_cast = lambda x: x

        self._dimension = kwargs.pop('dimension', 1)
        kwargs.setdefault('blank', True)
        kwargs.setdefault('null', True)
        kwargs.setdefault('default', None)
        super(ArrayField, self).__init__(*args, **kwargs)

    def get_db_prep_lookup(self, lookup_type, value, connection, prepared=False):
        if isinstance(value, (list, tuple)):
            return [value]
        return super(ArrayField, self).get_db_prep_lookup(lookup_type, value, connection, prepared)

    def formfield(self, **params):
        params.setdefault('form_class', ArrayFormField)
        return super(ArrayField, self).formfield(**params)

    def get_db_prep_value(self, value, connection, prepared=False):
        value = value if prepared else self.get_prep_value(value)
        if not value or isinstance(value, six.string_types):
            return value
        return _cast_to_type(value, self._type_cast)

    def get_prep_value(self, value):
        return value

    def to_python(self, value):
        return _unserialize(value)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return json.dumps(self.get_prep_value(value),
                          cls=DjangoJSONEncoder)

    def validate(self, value, model_instance):
        for val in value:
            super(ArrayField, self).validate(val, model_instance)

    if django.VERSION[:2] >= (1, 7):
        def deconstruct(self):
            name, path, args, kwargs = super(ArrayField, self).deconstruct()
            kwargs["dbtype"] = self._array_type
            kwargs["type_cast"] = self._type_cast
            kwargs["dimension"] = self._dimension
            return name, path, args, kwargs

        def db_parameters(self, connection):
            return {
                'type': '{0}{1}'.format(self._array_type, "[]" * self._dimension),
                'check': None
            }
    def db_type(self, connection):
        return '{0}{1}'.format(self._array_type, "[]" * self._dimension)


# South support
try:
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([
        (
            [ArrayField], # class
            [],           # positional params
            {
                "dbtype": ["_array_type", {"default": "int"}],
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ['^djorm_pgarray\.fields\.ArrayField'])
except ImportError:
    pass


class ArrayFormField(forms.Field):
    default_error_messages = {
        'invalid': _('Enter a list of values, joined by commas.  E.g. "a,b,c".'),
    }

    def __init__(self, max_length=None, min_length=None, delim=None,
                 strip=True, *args, **kwargs):
        if delim is not None:
            self.delim = delim
        else:
            self.delim = u','

        self.strip = strip

        super(ArrayFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if not value:
            return []
        # If Django already parsed value to list
        if isinstance(value, list):
            return value
        try:
            if self.strip:
                return map(unicode.strip, value.split(self.delim))
            else:
                return value.split(self.delim)
        except Exception:
            raise ValidationError(self.error_messages['invalid'])

    def prepare_value(self, value):
        if value:
            return self.delim.join(force_text(v) for v in value)

        return super(ArrayFormField, self).prepare_value(value)

    def to_python(self, value):
        return value.split(self.delim)



if django.VERSION[:2] >= (1, 7):
    from django.db.models import Lookup

    class ContainsLookup(Lookup):
        lookup_name = 'contains'

        def as_sql(self, qn, connection):
            lhs, lhs_params = self.process_lhs(qn, connection)
            rhs, rhs_params = self.process_rhs(qn, connection)
            params = lhs_params + rhs_params
            return '%s @> %s' % (lhs, rhs), params

    class ContainedByLookup(Lookup):
        lookup_name = "contained_by"

        def as_sql(self, qn, connection):
            lhs, lhs_params = self.process_lhs(qn, connection)
            rhs, rhs_params = self.process_rhs(qn, connection)
            params = lhs_params + rhs_params
            return '%s <@ %s' % (lhs, rhs), params

    class OverlapLookip(Lookup):
        lookup_name = "overlap"

        def as_sql(self, qn, connection):
            lhs, lhs_params = self.process_lhs(qn, connection)
            rhs, rhs_params = self.process_rhs(qn, connection)
            params = lhs_params + rhs_params
            return '%s && %s' % (lhs, rhs), params

    ArrayField.register_lookup(ContainedByLookup)
    ArrayField.register_lookup(ContainsLookup)
    ArrayField.register_lookup(OverlapLookip)
