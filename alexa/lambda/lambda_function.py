"""Alexa Smart Home Skill Lambda for Devialet Expert Amplifiers.

Handles Alexa Smart Home directives and communicates with Devialet Expert
amplifiers via AWS IoT Device Shadow.

Architecture:
    Alexa -> Lambda -> IoT Shadow <- MQTT <- Local Bridge -> UDP -> Devialet

Environment Variables:
    IOT_THING_NAMES: Comma-separated list of IoT Thing names
"""

import boto3
import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

iot_data = boto3.client('iot-data')

# Devialet volume: 0-255 internal, capped at 175 (-10dB) for safety.
# Alexa volume: 0-100 integer.
MAX_VOLUME_INT = 175


def lambda_handler(event, context):
    """Main entry point for Alexa Smart Home Skill."""
    logger.info("Event: %s", json.dumps(event))

    directive = event.get('directive', {})
    header = directive.get('header', {})
    namespace = header.get('namespace', '')
    name = header.get('name', '')

    if namespace == 'Alexa.Discovery':
        return handle_discovery(directive)
    elif namespace == 'Alexa.Authorization':
        return handle_authorization(directive)
    elif namespace == 'Alexa.PowerController':
        return handle_power_controller(directive)
    elif namespace == 'Alexa.Speaker':
        return handle_speaker(directive, name)
    elif namespace == 'Alexa.InputController':
        return handle_input_controller(directive)
    elif namespace == 'Alexa' and name == 'ReportState':
        return handle_report_state(directive)
    else:
        logger.error("Unsupported directive: %s.%s", namespace, name)
        return make_error_response(
            directive, 'INVALID_DIRECTIVE',
            f'Unsupported directive: {namespace}.{name}'
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_thing_names():
    names = os.environ.get('IOT_THING_NAMES', '')
    return [n.strip() for n in names.split(',') if n.strip()]


def get_shadow(thing_name):
    """Read the reported state from the device shadow."""
    try:
        response = iot_data.get_thing_shadow(thingName=thing_name)
        payload = json.loads(response['payload'].read())
        return payload.get('state', {}).get('reported', {})
    except iot_data.exceptions.ResourceNotFoundException:
        logger.warning("Shadow not found for %s", thing_name)
        return None
    except Exception as e:
        logger.error("Failed to get shadow for %s: %s", thing_name, e)
        return None


def update_shadow_desired(thing_name, desired_state):
    """Update the desired state in the device shadow."""
    try:
        payload = json.dumps({'state': {'desired': desired_state}})
        iot_data.update_thing_shadow(
            thingName=thing_name,
            payload=payload.encode(),
        )
        return True
    except Exception as e:
        logger.error("Failed to update shadow for %s: %s", thing_name, e)
        return False


def alexa_volume_to_devialet(alexa_vol):
    """Alexa 0-100 -> Devialet 0-175 (capped at -10 dB)."""
    return max(0, min(MAX_VOLUME_INT, round(alexa_vol * MAX_VOLUME_INT / 100)))


def devialet_volume_to_alexa(dev_vol):
    """Devialet 0-175 -> Alexa 0-100."""
    return max(0, min(100, round(dev_vol * 100 / MAX_VOLUME_INT)))


def get_endpoint_id(directive):
    return directive.get('endpoint', {}).get('endpointId', '')


def make_header(namespace, name, correlation_token=None):
    header = {
        'namespace': namespace,
        'name': name,
        'payloadVersion': '3',
        'messageId': str(uuid.uuid4()),
    }
    if correlation_token:
        header['correlationToken'] = correlation_token
    return header


def get_utc_timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.00Z')


def get_context_properties(reported):
    """Build Alexa context properties from reported shadow state."""
    now = get_utc_timestamp()
    props = []
    if reported is None:
        return props

    if 'power' in reported:
        props.append({
            'namespace': 'Alexa.PowerController',
            'name': 'powerState',
            'value': 'ON' if reported['power'] else 'OFF',
            'timeOfSample': now,
            'uncertaintyInMilliseconds': 5000,
        })

    if 'volume' in reported:
        props.append({
            'namespace': 'Alexa.Speaker',
            'name': 'volume',
            'value': devialet_volume_to_alexa(reported['volume']),
            'timeOfSample': now,
            'uncertaintyInMilliseconds': 5000,
        })

    if 'muted' in reported:
        props.append({
            'namespace': 'Alexa.Speaker',
            'name': 'muted',
            'value': reported['muted'],
            'timeOfSample': now,
            'uncertaintyInMilliseconds': 5000,
        })

    if 'source' in reported:
        props.append({
            'namespace': 'Alexa.InputController',
            'name': 'input',
            'value': reported['source'],
            'timeOfSample': now,
            'uncertaintyInMilliseconds': 5000,
        })

    props.append({
        'namespace': 'Alexa.EndpointHealth',
        'name': 'connectivity',
        'value': {'value': 'OK' if reported else 'UNREACHABLE'},
        'timeOfSample': now,
        'uncertaintyInMilliseconds': 5000,
    })

    return props


def make_error_response(directive, error_type, message):
    header = directive.get('header', {})
    return {
        'event': {
            'header': make_header(
                'Alexa', 'ErrorResponse',
                header.get('correlationToken'),
            ),
            'endpoint': directive.get('endpoint', {}),
            'payload': {'type': error_type, 'message': message},
        }
    }


# ---------------------------------------------------------------------------
# Directive Handlers
# ---------------------------------------------------------------------------

def handle_authorization(directive):
    """Accept account-linking grant (required even for dev skills)."""
    return {
        'event': {
            'header': make_header('Alexa.Authorization',
                                  'AcceptGrant.Response'),
            'payload': {},
        }
    }


def handle_discovery(directive):
    """Return all Devialet endpoints with their capabilities."""
    endpoints = []

    for thing_name in get_thing_names():
        reported = get_shadow(thing_name)

        inputs = []
        if reported and 'sources' in reported:
            for src in reported['sources']:
                inputs.append({'name': src})

        friendly_name = 'Devialet'
        if reported and 'name' in reported:
            friendly_name = reported['name']

        endpoint = {
            'endpointId': thing_name,
            'manufacturerName': 'Devialet',
            'description': 'Devialet Expert Amplifier',
            'friendlyName': friendly_name,
            'displayCategories': ['SPEAKER'],
            'capabilities': [
                {
                    'type': 'AlexaInterface',
                    'interface': 'Alexa.PowerController',
                    'version': '3',
                    'properties': {
                        'supported': [{'name': 'powerState'}],
                        'proactivelyReported': False,
                        'retrievable': True,
                    },
                },
                {
                    'type': 'AlexaInterface',
                    'interface': 'Alexa.Speaker',
                    'version': '3',
                    'properties': {
                        'supported': [
                            {'name': 'volume'},
                            {'name': 'muted'},
                        ],
                        'proactivelyReported': False,
                        'retrievable': True,
                    },
                },
                {
                    'type': 'AlexaInterface',
                    'interface': 'Alexa.InputController',
                    'version': '3',
                    'properties': {
                        'supported': [{'name': 'input'}],
                        'proactivelyReported': False,
                        'retrievable': True,
                    },
                    'inputs': inputs,
                },
                {
                    'type': 'AlexaInterface',
                    'interface': 'Alexa.EndpointHealth',
                    'version': '3',
                    'properties': {
                        'supported': [{'name': 'connectivity'}],
                        'proactivelyReported': False,
                        'retrievable': True,
                    },
                },
                {
                    'type': 'AlexaInterface',
                    'interface': 'Alexa',
                    'version': '3',
                },
            ],
        }
        endpoints.append(endpoint)

    return {
        'event': {
            'header': make_header('Alexa.Discovery', 'Discover.Response'),
            'payload': {'endpoints': endpoints},
        }
    }


def handle_power_controller(directive):
    """Handle TurnOn / TurnOff."""
    header = directive['header']
    endpoint_id = get_endpoint_id(directive)
    correlation = header.get('correlationToken')
    power_on = header['name'] == 'TurnOn'

    if not update_shadow_desired(endpoint_id, {'power': power_on}):
        return make_error_response(
            directive, 'INTERNAL_ERROR',
            'Failed to send command to device',
        )

    # Optimistic: assume the command will succeed.
    reported = get_shadow(endpoint_id) or {}
    reported['power'] = power_on

    return {
        'event': {
            'header': make_header('Alexa', 'Response', correlation),
            'endpoint': {'endpointId': endpoint_id},
            'payload': {},
        },
        'context': {'properties': get_context_properties(reported)},
    }


def handle_speaker(directive, name):
    """Handle SetVolume, AdjustVolume, SetMute."""
    header = directive['header']
    endpoint_id = get_endpoint_id(directive)
    correlation = header.get('correlationToken')
    payload = directive.get('payload', {})
    reported = get_shadow(endpoint_id) or {}

    if name == 'SetVolume':
        alexa_vol = payload.get('volume', 50)
        dev_vol = alexa_volume_to_devialet(alexa_vol)
        if not update_shadow_desired(endpoint_id, {'volume': dev_vol}):
            return make_error_response(
                directive, 'INTERNAL_ERROR', 'Failed to send command')
        reported['volume'] = dev_vol

    elif name == 'AdjustVolume':
        alexa_delta = payload.get('volume', 10)
        current_dev_vol = reported.get('volume', 0)
        current_alexa_vol = devialet_volume_to_alexa(current_dev_vol)
        new_alexa_vol = max(0, min(100, current_alexa_vol + alexa_delta))
        dev_vol = alexa_volume_to_devialet(new_alexa_vol)
        if not update_shadow_desired(endpoint_id, {'volume': dev_vol}):
            return make_error_response(
                directive, 'INTERNAL_ERROR', 'Failed to send command')
        reported['volume'] = dev_vol

    elif name == 'SetMute':
        muted = payload.get('mute', False)
        if not update_shadow_desired(endpoint_id, {'muted': muted}):
            return make_error_response(
                directive, 'INTERNAL_ERROR', 'Failed to send command')
        reported['muted'] = muted

    return {
        'event': {
            'header': make_header('Alexa', 'Response', correlation),
            'endpoint': {'endpointId': endpoint_id},
            'payload': {},
        },
        'context': {'properties': get_context_properties(reported)},
    }


def handle_input_controller(directive):
    """Handle SelectInput."""
    header = directive['header']
    endpoint_id = get_endpoint_id(directive)
    correlation = header.get('correlationToken')
    source_name = directive.get('payload', {}).get('input', '')

    if not update_shadow_desired(endpoint_id, {'source': source_name}):
        return make_error_response(
            directive, 'INTERNAL_ERROR', 'Failed to send command')

    reported = get_shadow(endpoint_id) or {}
    reported['source'] = source_name

    return {
        'event': {
            'header': make_header('Alexa', 'Response', correlation),
            'endpoint': {'endpointId': endpoint_id},
            'payload': {},
        },
        'context': {'properties': get_context_properties(reported)},
    }


def handle_report_state(directive):
    """Return current device state to Alexa."""
    header = directive['header']
    endpoint_id = get_endpoint_id(directive)
    correlation = header.get('correlationToken')
    reported = get_shadow(endpoint_id)

    if reported is None:
        return make_error_response(
            directive, 'BRIDGE_UNREACHABLE', 'Device is not reachable')

    return {
        'event': {
            'header': make_header('Alexa', 'StateReport', correlation),
            'endpoint': {'endpointId': endpoint_id},
            'payload': {},
        },
        'context': {'properties': get_context_properties(reported)},
    }
