import copy
from .string_utilities import StringUtilities

class DictionaryUtilities:

    @staticmethod
    def add_common_keys(add_to, add_from, skip_keys=['date']) -> dict:
        """
        adds value of common keys' to the first dictionary 'add_to'
        """
        if not isinstance(add_to, dict) or not isinstance(add_from, dict):
            raise TypeError
        for key in add_to.keys():
            if key in skip_keys:
                continue
            if key in add_from.keys():
                if isinstance(add_to[key], dict) and isinstance(add_from[key], dict):
                    add_to[key] = DictionaryUtilities.add_common_keys(add_to[key], add_from[key], skip_keys=skip_keys)
                elif type(add_to[key]) is type(add_from[key]):
                    add_to[key] += copy.deepcopy(add_from[key])
        return add_to


    @staticmethod
    def merge_nested_dictionary(merge_to, merge_from, skip_keys=['date'], overwrite_common=False) -> dict:
        if not isinstance(merge_to, dict) or not isinstance(merge_from, dict):
            raise TypeError
        for key in merge_from.keys():
            if key in skip_keys:
                continue
            if key in merge_to:
                if isinstance(merge_to[key], dict) and isinstance(merge_from[key], dict):
                    merge_to[key] = DictionaryUtilities.merge_nested_dictionary(merge_to[key], merge_from[key], skip_keys=skip_keys, overwrite_common=overwrite_common)
                elif overwrite_common:
                    merge_to[key] = copy.deepcopy(merge_from[key])
            else:
                merge_to[key] = copy.deepcopy(merge_from[key])

        return merge_to

    @staticmethod
    def model_instance_to_dict(model_instance):

        data = {}
        if model_instance:
            for field in model_instance._meta.fields:
                data[field.attname] =StringUtilities.convert_object_to_string(getattr(model_instance, field.attname))

        return data 
