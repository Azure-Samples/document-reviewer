from azure_functions_agents import create_function_app

from document_review.trigger_payloads import install_connector_trigger_normalizer


install_connector_trigger_normalizer()
app = create_function_app()
