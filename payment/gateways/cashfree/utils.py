from decimal import Decimal
from  ...models import Payment
from ....utilities.json_utilities import JsonUtilities

def get_error_response(amount: Decimal, **additional_kwargs) -> dict:
    """Create a placeholder response for invalid or failed requests.

    It is used to generate a failed transaction object.
    """
    return {"is_success": False, "amount": amount, **additional_kwargs}


def get_cashfree_order_id_from_payment(root: Payment):
    extra_data = JsonUtilities.loads(root.extra_data).get('order_id',"")
    return extra_data


