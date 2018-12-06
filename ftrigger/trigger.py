import logging
import os
import re
import time
from collections import ChainMap

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


log = logging.getLogger(__name__)


class Functions(object):

    def __init__(self, label='ftrigger', name=None, refresh_interval=5, gateway='http://gateway:8080'):
        self.refresh_interval = int(os.getenv('TRIGGER_REFRESH_INTERVAL', refresh_interval))
        self.last_refresh = 0
        self._functions = {}
        self._stack_namespace = os.getenv('STACK_NAMESPACE', None)
        self._label = os.getenv('TRIGGER_LABEL', label)
        self._name = os.getenv('TRIGGER_NAME', name)
        self._register_label = f'{label}.{name}'
        self._argument_pattern = re.compile(f'^{label}\\.{name}\\.([^.]+)$')
        self._gateway_base = gateway.rstrip('/')
        self.gateway = requests.Session()
        self.gateway.mount(self._gateway_base, HTTPAdapter(max_retries=Retry(
            total=None,
            connect=int(os.getenv('GATEWAY_RETRY', 10)),
            read=10,
            redirect=10,
            backoff_factor=0.1,
            method_whitelist=frozenset(['HEAD', 'GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'TRACE'])
        )))

    @property
    def label(self):
        return self._label

    @property
    def name(self):
        return self._name

    def refresh(self, force=False):
        if not force and time.time() - self.last_refresh < self.refresh_interval:
            return [], [], []

        add_functions = []
        update_functions = []
        remove_functions = []

        functions = self.gateway.get(self._gateway_base + '/system/functions').json()
        if self._stack_namespace:
            functions = filter(lambda f: f.get('labels', {}).get('com.docker.stack.namespace') == self._stack_namespace, functions)
        functions = list(filter(lambda f: self._register_label in ChainMap((f.get('labels') or {}), (f.get('annotations') or {})), functions))

        # Scan for new and updated functions
        for function in functions:
            existing_function = self._functions.get(function['name'])

            if not existing_function:
                # register a new function
                log.debug(f'Add function: {function["name"]}')
                add_functions.append(function)
                self._functions[function['name']] = function
            elif False:
            # elif function['service'].attrs['UpdatedAt'] > existing_function['service'].attrs['UpdatedAt']:
                # maybe update an already registered function
                log.debug(f'Update function: {function["name"]}')
                update_functions.append(function)
                self._functions[function['name']] = function

        # Scan for removed functions
        for function_name in set(self._functions.keys()) - set([f['name'] for f in functions]):
            function = self._functions.pop(function_name)
            log.debug(f'Remove function: {function["name"]}')
            remove_functions.append(function)

        self.last_refresh = time.time()
        return add_functions, update_functions, remove_functions

    def arguments(self, function):
        labels = ChainMap((f.get('labels') or {}), (f.get('annotations') or {}))
        
        if self._register_label not in labels:
            return None

        args = {m.group(1): v for m, v
                in [(self._argument_pattern.match(k), v) for k, v in labels.items()] if m}
        log.debug(f'{function["name"]} arguments: {args}')
        return args
