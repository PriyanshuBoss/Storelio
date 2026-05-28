"""Module to define some utils non related to business logic.

Notes
-----
The function defined here must be context and implementation independant, for
easy reusability
"""
import requests
import json
from pathlib import Path
from django.core.serializers.json import DjangoJSONEncoder



def override_dict(a, overrides):
    """Override a dict with another one **only first non nested keys**.

    Notes
    -----
    This works only with non-nested dict. If dictionarries are nested then the
    nested dict needs to be completly overriden.
    The Operation is performed inplace.

    Parameters
    ----------
    a : dict
        a dictionary to merge.
    overrides : dict
        another dictionary to merge.
    """
    for key, val in overrides.items():
        try:
            if type(a[key]) == dict:
                print(
                    "**warning**: key '{}' contained a dict make sure to override each value in the nested dict.".format(key))
        except KeyError:
            pass
        a[key] = val


def handle_errors(errors):
    """Handle a list of errors as dict with keys message and field.

    Parameters
    ----------
    error : list
        a list of errors each error must be a dict with at least the following
        keys: `field` and `message`

    Raises
    ------
    Exception
        when the list is not empty and display {field} : {message} errors.
    """
    if len(errors) > 0:
        txt_list = [
            "{field} : {message}".format(**error) for error in errors]
        raise Exception("\n".join(txt_list))

def get_operations(product_id):
    """Get ProductImageCreate operations

    Parameters
    ----------
    product_id : str
            id for which the product image will be created.

    Returns
    -------
    query : str
    variables: dict
    """
    query = """
        mutation ProductImageCreate($product: ID!, $image: Upload!, $alt: String) {
            productImageCreate(input: {alt: $alt, image: $image, product: $product}) {
                image{
                    id
                }
                productErrors {
                    field
                    message
                }
            }
        }
    """
    variables = {
        "product": product_id,
        "image": "0",
        "alt": ''
    }
    return {"query": query, "variables": variables}

def get_payload(product_id, file_path):
    """Get ProductImageCreate operations

    Parameters
    ----------
    product_id : str
            id for which the product image will be created.

    Returns
    -------
    query : str
    variables: dict
    """
    return {
        "operations": json.dumps(
            get_operations(product_id), cls=DjangoJSONEncoder
        ),
        "map": json.dumps({'0': ["variables.image"]}, cls=DjangoJSONEncoder),
        "0": (Path(file_path).name, open(file_path, 'rb'), 'image/png')
    }
