from typing import TYPE_CHECKING

from saleor.plugins.base_plugin import BasePlugin, ConfigurationTypeField

from ..utils import get_supported_currencies
from . import GatewayConfig, capture, process_payment, refund, create_order_id

GATEWAY_NAME = "Cashfree"

if TYPE_CHECKING:
    from . import GatewayResponse, PaymentData


def require_active_plugin(fn):
    def wrapped(self, *args, **kwargs):
        previous = kwargs.get("previous_value", None)
        if not self.active:
            return previous
        return fn(self, *args, **kwargs)

    return wrapped


class CashfreeGatewayPlugin(BasePlugin):
    PLUGIN_NAME = GATEWAY_NAME
    PLUGIN_ID = "zaamo.payments.cashfree"
    DEFAULT_CONFIGURATION = [
        {"name": "Public API key", "value": None},
        {"name": "Secret API key", "value": None},
        {"name": "Store customers card", "value": False},
        {"name": "Automatic payment capture", "value": True},
        {"name": "API Version","value":None},
        {"name": "Supported currencies", "value": ""},
    ]

    CONFIG_STRUCTURE = {
        "Public API key": {
            "type": ConfigurationTypeField.SECRET,
            "help_text": "Provide  public API key.",
            "label": "Public API key",
        },
        "Secret API key": {
            "type": ConfigurationTypeField.SECRET,
            "help_text": "Provide Stripe secret API key.",
            "label": "Secret API key",
        },
        "Store customers card": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Determines if Saleor should store cards on payments "
            "in Stripe customer.",
            "label": "Store customers card",
        },
        "Automatic payment capture": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Determines if Saleor should automaticaly capture payments.",
            "label": "Automatic payment capture",
        },
        "API Version": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Provide Cashfree API Version.",
            "label": "API Version",
        },
        "Supported currencies": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Determines currencies supported by gateway."
            " Please enter currency codes separated by a comma.",
            "label": "Supported currencies",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configuration = {item["name"]: item["value"] for item in self.configuration}
        self.config = GatewayConfig(
            gateway_name=GATEWAY_NAME,
            auto_capture=configuration["Automatic payment capture"],
            supported_currencies=configuration["Supported currencies"],
            connection_params={
                "public_key": configuration["Public API key"],
                "private_key": configuration["Secret API key"],
                "api_version":configuration["API Version"],
                "prefill": True,
                "store_name": None,
                "store_image": None,
            },
            store_customer=configuration["Store customers card"],
        )

    def _get_gateway_config(self):
        return self.config

    @require_active_plugin
    def capture_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return capture(payment_information, self._get_gateway_config())

    @require_active_plugin
    def refund_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return refund(payment_information, self._get_gateway_config())

    @require_active_plugin
    def process_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return process_payment(payment_information, self._get_gateway_config())

    @require_active_plugin
    def create_order_id(self, payment_information: "PaymentData", previous_value) -> "GatewayResponse":
        return create_order_id(payment_information, self._get_gateway_config())

    @require_active_plugin
    def get_supported_currencies(self, previous_value):
        config = self._get_gateway_config()
        return get_supported_currencies(config, GATEWAY_NAME)

    @require_active_plugin
    def get_payment_config(self, previous_value):
        config = self._get_gateway_config()
        return [{"field": "api_key", "value": config.connection_params["public_key"],
                "field":"api_version", "value": config.connection_params["api_version"]}]
