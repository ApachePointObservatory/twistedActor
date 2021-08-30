#!/usr/bin/env python
# encoding: utf-8
#
# @Author: José Sánchez-Gallego
# @Date: Mar 8, 2018
# @Filename: hub.py
# @License: BSD 3-Clause
# @Copyright: José Sánchez-Gallego


from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import re

from . import device


class HubConnection(device.TCPDevice):
    """A device connection to the Hub.

    This class implments a `~device.TCPDevice` connection to the Hub that
    listens for new keywords and updates a datamodel.

    Parameters:
        host (str):
            The host where the hub is running.
        port (int):
            The port on which the hub is running.
        use_datamodel (bool):
            Whether the connection should listen for new keywords from the
            Hub and update a datamodel.
        datamodel_casts (dict):
            A dictionary of the form ``'actor.keyword': func`` that defines
            how to cast the values of that keyword.
            E.g., ``{'guider.cartridgeLoaded': int}``.
        datamodel_callbacks (dict):
            A dictionary, similar to ``datamodel_casts`` with a callback
            function to call when the keywords gets updated.

    """

    def __init__(self, host, port=6093, use_datamodel=True,
                 datamodel_casts=None, datamodel_callbacks=None, **kwargs):

        device.TCPDevice.__init__(self, name='hub', host=host, port=port, **kwargs)
        self.connect()

        if use_datamodel:
            self.datamodel = HubModel(casts=datamodel_casts, callbacks=datamodel_callbacks)
        else:
            self.datamodel = None

    def init(self, userCmd=None, timeLim=None, getStatus=True):
        pass

    def handleReply(self, reply_str):

        if self.datamodel is None:
            return

        reply_str = reply_str.strip()

        if not reply_str:
            return

        matched = re.match(r'^(?P<commanderID>.+) (?P<cmdID>[0-9]+) '
                           r'(?P<userID>.+) (?P<severity>[a-z,A-Z,:]) '
                           r'(?P<cmd>.+)$', reply_str)

        if matched:

            group = matched.groupdict()

            if group['userID'] in ['cmds', 'keys']:
                return

            # keypairs = re.findall('(.+)=(.+);*', group['cmd'])

            keyvalue_pairs = map(lambda x: x.strip(), group['cmd'].split(';'))

            for pair in keyvalue_pairs:

                if '=' not in pair:
                    key = pair
                    value = None
                else:
                    key, value = pair.split('=', 1)

                actor = group['userID']

                if actor not in self.datamodel:
                    self.datamodel.add_model(actor)

                self.datamodel[actor][key] = value


class ActorModel(dict):
    """A dictionary defining a datamodel for an actor.

    Parameters:
        name (str):
            The name of the actor.
        casts (dict):
            A dictionary of the form ``'keyword': func`` that defines
            how to cast the values of that keyword.
            E.g., ``{'cartridgeLoaded': int}``.
        callbacks (dict):
            A dictionary, similar to ``datamodel_casts`` with a callback
            function to call when the keywords gets updated.

    """

    def __init__(self, name, casts=None, callbacks=None):

        super(ActorModel, self).__init__()

        self.name = name
        self.casts = casts or dict()
        self.callbacks = callbacks or dict()

    def __setitem__(self, key, value):

        def try_cast(value):
            try:
                return self.casts[key](value)
            except ValueError:
                return value

        unquoted = list(map(lambda xx: re.sub(r'^"|"$', '', xx), str(value).split(',')))

        if key in self.casts:
            dict.__setitem__(self, key, list(map(try_cast, unquoted)))
        else:
            dict.__setitem__(self, key, unquoted)

        if key in self.callbacks:
            self.callbacks[key](dict.__getitem__(self, key))


class HubModel(dict):
    """A dictionary defining a datamodel for multiple actors.

    Parameters:
        casts (dict):
            A dictionary of the form ``'actor.keyword': func`` that defines
            how to cast the values of that keyword.
            E.g., ``{'guider.cartridgeLoaded': int}``.
        callbacks (dict):
            A dictionary, similar to ``casts`` with a callback function to
            call when the keywords gets updated.

    """

    def __init__(self, casts=None, callbacks=None):

        casts = casts or dict()
        callbacks = callbacks or dict()

        super(HubModel, self).__init__()

        # Creates a list of all actors defined in casts or callbacks
        actors = list(set(self._parse_actors(casts) + self._parse_actors(callbacks)))

        for actor in actors:

            # For each actor, creates a list of casts and callbacks stripping
            # the actor part from the dictionary.
            # E.g., {'guider.cartridgeLoaded': int} -> {'cartridgeLoaded': int}

            actor_casts = dict((keyword.split('.')[1], cast)
                               for keyword, cast in casts.items()
                               if keyword.split('.')[0] == actor)

            actor_cbs = dict((keyword.split('.')[1], cb)
                             for keyword, cb in callbacks.items()
                             if keyword.split('.')[0] == actor)

            self.add_model(actor, casts=actor_casts, callbacks=actor_cbs)

    @staticmethod
    def _parse_actors(values):

        return list(map(lambda xx: xx.split('.')[0], list(values)))

    def add_model(self, actor_name, casts={}, callbacks={}):
        """Adds a new actor to the datamodel.

        Parameters:
            actor_name (str):
                The name of the actor.
            casts (dict):
                A dictionary of the form ``'keyword': func`` that defines
                how to cast the values of that keyword.
                E.g., ``{'cartridgeLoaded': int}``.
            callbacks (dict):
                A dictionary, similar to ``datamodel_casts`` with a callback
                function to call when the keywords gets updated.

        """

        model = ActorModel(actor_name, casts=casts, callbacks=callbacks)
        self[actor_name] = model

    def __setitem__(self, key, value):

        if key in self:
            raise ValueError('actor {!r} already in the model'.format(value))

        assert isinstance(value, ActorModel), 'value being set must be an ActorModel'

        dict.__setitem__(self, key, value)
