# -*- coding: utf-8 -*-
# Copyright 2015 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import simplejson
from simplejson import JSONDecodeError
from twisted.internet import defer

from synapse.api.constants import Membership
from synapse.api.errors import StoreError
from synapse.appservice import ApplicationService
from synapse.storage.roommember import RoomsForUser
from ._base import SQLBaseStore


logger = logging.getLogger(__name__)


def log_failure(failure):
    logger.error("Failed to detect application services: %s", failure.value)
    logger.error(failure.getTraceback())


class ApplicationServiceStore(SQLBaseStore):

    def __init__(self, hs):
        super(ApplicationServiceStore, self).__init__(hs)
        self.services_cache = []
        self.cache_defer = self._populate_cache()
        self.cache_defer.addErrback(log_failure)

    @defer.inlineCallbacks
    def unregister_app_service(self, token):
        """Unregisters this service.

        This removes all AS specific regex and the base URL. The token is the
        only thing preserved for future registration attempts.
        """
        yield self.cache_defer  # make sure the cache is ready
        yield self.runInteraction(
            "unregister_app_service",
            self._unregister_app_service_txn,
            token,
        )
        # update cache TODO: Should this be in the txn?
        for service in self.services_cache:
            if service.token == token:
                service.url = None
                service.namespaces = None
                service.hs_token = None

    def _unregister_app_service_txn(self, txn, token):
        # kill the url to prevent pushes
        txn.execute(
            "UPDATE application_services SET url=NULL WHERE token=?",
            (token,)
        )

        # cleanup regex
        as_id = self._get_as_id_txn(txn, token)
        if not as_id:
            logger.warning(
                "unregister_app_service_txn: Failed to find as_id for token=",
                token
            )
            return False

        txn.execute(
            "DELETE FROM application_services_regex WHERE as_id=?",
            (as_id,)
        )
        return True

    @defer.inlineCallbacks
    def update_app_service(self, service):
        """Update an application service, clobbering what was previously there.

        Args:
            service(ApplicationService): The updated service.
        """
        yield self.cache_defer  # make sure the cache is ready

        # NB: There is no "insert" since we provide no public-facing API to
        # allocate new ASes. It relies on the server admin inserting the AS
        # token into the database manually.

        if not service.token or not service.url:
            raise StoreError(400, "Token and url must be specified.")

        if not service.hs_token:
            raise StoreError(500, "No HS token")

        yield self.runInteraction(
            "update_app_service",
            self._update_app_service_txn,
            service
        )

        # update cache TODO: Should this be in the txn?
        for (index, cache_service) in enumerate(self.services_cache):
            if service.token == cache_service.token:
                self.services_cache[index] = service
                logger.info("Updated: %s", service)
                return
        # new entry
        self.services_cache.append(service)
        logger.info("Updated(new): %s", service)

    def _update_app_service_txn(self, txn, service):
        as_id = self._get_as_id_txn(txn, service.token)
        if not as_id:
            logger.warning(
                "update_app_service_txn: Failed to find as_id for token=",
                service.token
            )
            return False

        txn.execute(
            "UPDATE application_services SET url=?, hs_token=?, sender=? "
            "WHERE id=?",
            (service.url, service.hs_token, service.sender, as_id,)
        )
        # cleanup regex
        txn.execute(
            "DELETE FROM application_services_regex WHERE as_id=?",
            (as_id,)
        )
        for (ns_int, ns_str) in enumerate(ApplicationService.NS_LIST):
            if ns_str in service.namespaces:
                for regex_obj in service.namespaces[ns_str]:
                    txn.execute(
                        "INSERT INTO application_services_regex("
                        "as_id, namespace, regex) values(?,?,?)",
                        (as_id, ns_int, simplejson.dumps(regex_obj))
                    )
        return True

    def _get_as_id_txn(self, txn, token):
        cursor = txn.execute(
            "SELECT id FROM application_services WHERE token=?",
            (token,)
        )
        res = cursor.fetchone()
        if res:
            return res[0]

    @defer.inlineCallbacks
    def get_app_services(self):
        yield self.cache_defer  # make sure the cache is ready
        defer.returnValue(self.services_cache)

    @defer.inlineCallbacks
    def get_app_service_by_user_id(self, user_id):
        """Retrieve an application service from their user ID.

        All application services have associated with them a particular user ID.
        There is no distinguishing feature on the user ID which indicates it
        represents an application service. This function allows you to map from
        a user ID to an application service.

        Args:
            user_id(str): The user ID to see if it is an application service.
        Returns:
            synapse.appservice.ApplicationService or None.
        """

        yield self.cache_defer  # make sure the cache is ready

        for service in self.services_cache:
            if service.sender == user_id:
                defer.returnValue(service)
                return
        defer.returnValue(None)

    @defer.inlineCallbacks
    def get_app_service_by_token(self, token, from_cache=True):
        """Get the application service with the given appservice token.

        Args:
            token (str): The application service token.
            from_cache (bool): True to get this service from the cache, False to
                               check the database.
        Raises:
            StoreError if there was a problem retrieving this service.
        """
        yield self.cache_defer  # make sure the cache is ready

        if from_cache:
            for service in self.services_cache:
                if service.token == token:
                    defer.returnValue(service)
                    return
            defer.returnValue(None)

        # TODO: The from_cache=False impl
        # TODO: This should be JOINed with the application_services_regex table.

    def get_app_service_rooms(self, service):
        """Get a list of RoomsForUser for this application service.

        Application services may be "interested" in lots of rooms depending on
        the room ID, the room aliases, or the members in the room. This function
        takes all of these into account and returns a list of RoomsForUser which
        represent the entire list of room IDs that this application service
        wants to know about.

        Args:
            service: The application service to get a room list for.
        Returns:
            A list of RoomsForUser.
        """
        return self.runInteraction(
            "get_app_service_rooms",
            self._get_app_service_rooms_txn,
            service,
        )

    def _get_app_service_rooms_txn(self, txn, service):
        # get all rooms matching the room ID regex.
        room_entries = self._simple_select_list_txn(
            txn=txn, table="rooms", keyvalues=None, retcols=["room_id"]
        )
        matching_room_list = set([
            r["room_id"] for r in room_entries if
            service.is_interested_in_room(r["room_id"])
        ])

        # resolve room IDs for matching room alias regex.
        room_alias_mappings = self._simple_select_list_txn(
            txn=txn, table="room_aliases", keyvalues=None,
            retcols=["room_id", "room_alias"]
        )
        matching_room_list |= set([
            r["room_id"] for r in room_alias_mappings if
            service.is_interested_in_alias(r["room_alias"])
        ])

        # get all rooms for every user for this AS. This is scoped to users on
        # this HS only.
        user_list = self._simple_select_list_txn(
            txn=txn, table="users", keyvalues=None, retcols=["name"]
        )
        user_list = [
            u["name"] for u in user_list if
            service.is_interested_in_user(u["name"])
        ]
        rooms_for_user_matching_user_id = set()  # RoomsForUser list
        for user_id in user_list:
            # FIXME: This assumes this store is linked with RoomMemberStore :(
            rooms_for_user = self._get_rooms_for_user_where_membership_is_txn(
                txn=txn,
                user_id=user_id,
                membership_list=[Membership.JOIN]
            )
            rooms_for_user_matching_user_id |= set(rooms_for_user)

        # make RoomsForUser tuples for room ids and aliases which are not in the
        # main rooms_for_user_list - e.g. they are rooms which do not have AS
        # registered users in it.
        known_room_ids = [r.room_id for r in rooms_for_user_matching_user_id]
        missing_rooms_for_user = [
            RoomsForUser(r, service.sender, "join") for r in
            matching_room_list if r not in known_room_ids
        ]
        rooms_for_user_matching_user_id |= set(missing_rooms_for_user)

        return rooms_for_user_matching_user_id

    @defer.inlineCallbacks
    def _populate_cache(self):
        """Populates the ApplicationServiceCache from the database."""
        sql = ("SELECT * FROM application_services LEFT JOIN "
               "application_services_regex ON application_services.id = "
               "application_services_regex.as_id")
        # SQL results in the form:
        # [
        #   {
        #     'regex': "something",
        #     'url': "something",
        #     'namespace': enum,
        #     'as_id': 0,
        #     'token': "something",
        #     'hs_token': "otherthing",
        #     'id': 0
        #   }
        # ]
        services = {}
        results = yield self._execute_and_decode("_populate_cache", sql)
        for res in results:
            as_token = res["token"]
            if as_token not in services:
                # add the service
                services[as_token] = {
                    "url": res["url"],
                    "token": as_token,
                    "hs_token": res["hs_token"],
                    "sender": res["sender"],
                    "namespaces": {
                        ApplicationService.NS_USERS: [],
                        ApplicationService.NS_ALIASES: [],
                        ApplicationService.NS_ROOMS: []
                    }
                }
            # add the namespace regex if one exists
            ns_int = res["namespace"]
            if ns_int is None:
                continue
            try:
                services[as_token]["namespaces"][
                    ApplicationService.NS_LIST[ns_int]].append(
                    simplejson.loads(res["regex"])
                )
            except IndexError:
                logger.error("Bad namespace enum '%s'. %s", ns_int, res)
            except JSONDecodeError:
                logger.error("Bad regex object '%s'", res["regex"])

        # TODO get last successful txn id f.e. service
        for service in services.values():
            logger.info("Found application service: %s", service)
            self.services_cache.append(ApplicationService(
                token=service["token"],
                url=service["url"],
                namespaces=service["namespaces"],
                hs_token=service["hs_token"],
                sender=service["sender"]
            ))
