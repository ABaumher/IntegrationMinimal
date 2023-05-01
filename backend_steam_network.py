import asyncio
import logging
import ssl
from contextlib import suppress
from distutils.util import strtobool
from typing import Callable, List, Any, Dict, Union
from urllib import parse

from galaxy.api.errors import (
    AuthenticationRequired,
    UnknownBackendResponse,
    UnknownError,
    BackendTimeout,
)
from galaxy.api.types import (
    Game,
    LicenseInfo,
    LicenseType,
    UserInfo,
    UserPresence,
    Subscription,
    SubscriptionDiscovery,
    SubscriptionGame,
    Achievement,
    GameLibrarySettings,
    GameTime,
    Authentication, NextStep,
)

from backend_interface import BackendInterface
from http_client import HttpClient
from user_profile import UserProfileChecker, ProfileIsNotPublic, ProfileDoesNotExist, NotPublicGameDetailsOrUserHasNoGames
from steam_network.authentication import StartUri, EndUri, next_step_response
from steam_network.protocol.types import ProtoUserInfo  # TODO accessing inner module
from steam_network.steam_http_client import SteamHttpClient
from steam_network.websocket_client import WebSocketClient, UserActionRequired
from steam_network.websocket_list import WebSocketList

logger = logging.getLogger(__name__)


GAME_CACHE_IS_READY_TIMEOUT = 90
USER_INFO_CACHE_INITIALIZED_TIMEOUT = 30

GAME_DOES_NOT_SUPPORT_LAST_PLAYED_VALUE = 86400
STEAMCOMMUNITY_PROFILE_BASE_URL = "https://steamcommunity.com/profiles/"
AVATAR_URL_TEMPLATE = "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/avatars/{}/{}_full.jpg"
NO_AVATAR_SET = "0000000000000000000000000000000000000000"
DEFAULT_AVATAR_HASH = "fef49e7fa7e1997310d705b2a6158ff8dc1cdfeb"


def avatar_url_from_avatar_hash(a_hash: str):
    if a_hash == NO_AVATAR_SET:
        a_hash = DEFAULT_AVATAR_HASH
    return AVATAR_URL_TEMPLATE.format(a_hash[0:2], a_hash)


class SteamNetworkBackend(BackendInterface):
    def __init__(
        self,
        *,
        http_client: HttpClient,
        user_profile_checker: UserProfileChecker,
        ssl_context: ssl.SSLContext, 
    ) -> None:

        self._user_profile_checker = user_profile_checker

        steam_http_client = SteamHttpClient(http_client)
        self._websocket_client = WebSocketClient(
            WebSocketList(steam_http_client),
            ssl_context
        )
        self._auth_data = None
    
    def register_auth_lost_callback(self, callback: Callable):
        self._websocket_client.authentication_lost_handler = callback

    async def shutdown(self):
        await self._websocket_client.close()
        await self._websocket_client.wait_closed()

        await self._cancel_task(self._update_owned_games_task)
        await self._cancel_task(self._steam_run_task)

    async def _cancel_task(self, task):
        with suppress(asyncio.CancelledError):
            task.cancel()
            await task

    def tick(self):
        pass

    # authentication

    async def _get_websocket_auth_step(self):
        try:
            result = await asyncio.wait_for(
                self._websocket_client.communication_queues["plugin"].get(), 60
            )
            return result["auth_result"]
        except asyncio.TimeoutError:
            raise BackendTimeout()

    async def pass_login_credentials(self, step, credentials, cookies):
        if "login_finished" in credentials["end_uri"]:
            return await self._handle_login_finished(credentials)
        if "two_factor_mobile_finished" in credentials["end_uri"]:
            return await self._handle_two_step_mobile_finished(credentials)
        if "two_factor_mail_finished" in credentials["end_uri"]:
            return await self._handle_two_step_email_finished(credentials)
        if "public_prompt_finished" in credentials["end_uri"]:
            return await self._handle_public_prompt_finished(credentials)

    async def _handle_login_finished(self, credentials):
        parsed_url = parse.urlsplit(credentials["end_uri"])

        params = parse.parse_qs(parsed_url.query)
        if "username" not in params or "password" not in params:
            return next_step_response(StartUri.LOGIN_FAILED, EndUri.LOGIN_FINISHED)

        username = params["username"][0]
        password = params["password"][0]
        self._user_info_cache.account_username = username
        self._auth_data = [username, password]
        await self._websocket_client.communication_queues["websocket"].put({"password": password})
        result = await self._get_websocket_auth_step()
        if result == UserActionRequired.NoActionRequired:
            self._auth_data = None
            self._store_credentials(self._user_info_cache.to_dict())
            return await self._check_public_profile()
        if result == UserActionRequired.EmailTwoFactorInputRequired:
            return next_step_response(StartUri.TWO_FACTOR_MAIL, EndUri.TWO_FACTOR_MAIL_FINISHED)
        if result == UserActionRequired.PhoneTwoFactorInputRequired:
            return next_step_response(StartUri.TWO_FACTOR_MOBILE, EndUri.TWO_FACTOR_MOBILE_FINISHED)
        else:
            return next_step_response(StartUri.LOGIN_FAILED, EndUri.LOGIN_FINISHED)

    async def _handle_two_step(self, params, fail, finish):
        if "code" not in params:
            return next_step_response(fail, finish)

        two_factor = params["code"][0]
        await self._websocket_client.communication_queues["websocket"].put(
            {"password": self._auth_data[1], "two_factor": two_factor}
        )
        result = await self._get_websocket_auth_step()
        logger.info(f"2fa result {result}")
        if result != UserActionRequired.NoActionRequired:
            return next_step_response(fail, finish)
        else:
            self._auth_data = None
            self._store_credentials(self._user_info_cache.to_dict())
            return await self._check_public_profile()

    async def _handle_two_step_mobile_finished(self, credentials):
        parsed_url = parse.urlsplit(credentials["end_uri"])
        params = parse.parse_qs(parsed_url.query)
        return await self._handle_two_step(
            params, StartUri.TWO_FACTOR_MOBILE_FAILED, EndUri.TWO_FACTOR_MOBILE_FINISHED
        )

    async def _handle_two_step_email_finished(self, credentials):
        parsed_url = parse.urlsplit(credentials["end_uri"])
        params = parse.parse_qs(parsed_url.query)

        if "resend" in params:
            await self._websocket_client.communication_queues["websocket"].put(
                {"password": self._auth_data[1]}
            )
            await self._get_websocket_auth_step()  # Clear the queue
            return next_step_response(StartUri.TWO_FACTOR_MAIL, EndUri.TWO_FACTOR_MAIL_FINISHED)

        return await self._handle_two_step(
            params, StartUri.TWO_FACTOR_MAIL_FAILED, EndUri.TWO_FACTOR_MAIL_FINISHED
        )

    async def _handle_public_prompt_finished(self, credentials):
        parsed_url = parse.urlsplit(credentials["end_uri"])
        params = dict(parse.parse_qsl(parsed_url.query))
        user_wants_pp_fallback = strtobool(params.get("public_profile_fallback"))
        if user_wants_pp_fallback:
            return await self._check_public_profile()
        return Authentication(self._user_info_cache.steam_id, self._user_info_cache.persona_name)

    async def _check_public_profile(self) -> Union[Authentication, NextStep]:
        try:
            await self._user_profile_checker.check_is_public_by_steam_id(self._user_info_cache.steam_id)
        except ProfileIsNotPublic:
            logger.debug(f"Profile with Steam64 ID: `{self._user_info_cache.steam_id}` is not public")
            return next_step_response(StartUri.PP_PROMPT__PROFILE_IS_NOT_PUBLIC, EndUri.PUBLIC_PROMPT_FINISHED)
        except NotPublicGameDetailsOrUserHasNoGames:
            logger.debug(f"Profile with Steam64 ID: `{self._user_info_cache.steam_id}` has private games library or has no games")
            return next_step_response(StartUri.PP_PROMPT__NOT_PUBLIC_GAME_DETAILS_OR_USER_HAS_NO_GAMES, EndUri.PUBLIC_PROMPT_FINISHED)
        except ProfileDoesNotExist:
            logger.warning(f"Profile with provided Steam64 ID: `{self._user_info_cache.steam_id}` does not exist")
            raise UnknownBackendResponse()
        except ValueError:
            logger.warning(f"Incorrect provided Steam64 ID: `{self._user_info_cache.steam_id}`")
            raise UnknownBackendResponse()
        except Exception:
            return next_step_response(StartUri.PP_PROMPT__UNKNOWN_ERROR, EndUri.PUBLIC_PROMPT_FINISHED)
        else:
            return Authentication(
                self._user_info_cache.steam_id, self._user_info_cache.persona_name
            )

    async def authenticate(self, stored_credentials=None):
        if stored_credentials is None:
            self._steam_run_task = asyncio.create_task(self._websocket_client.run())
            return next_step_response(StartUri.LOGIN, EndUri.LOGIN_FINISHED)
        return await self._authenticate_with_stored_credentials(stored_credentials)
    
    async def _authenticate_with_stored_credentials(self, stored_credentials):
        self._user_info_cache.from_dict(stored_credentials)

        self._steam_run_task = asyncio.create_task(self._websocket_client.run())
        user_info_ready_task = asyncio.create_task(self._user_info_cache.initialized.wait())

        done, _ = await asyncio.wait(
            {self._steam_run_task, user_info_ready_task},
            timeout = USER_INFO_CACHE_INITIALIZED_TIMEOUT,
            return_when = asyncio.FIRST_COMPLETED
        )
        
        if user_info_ready_task in done:
            self._store_credentials(self._user_info_cache.to_dict())
            return Authentication(self._user_info_cache.steam_id, self._user_info_cache.persona_name)
        elif self._steam_run_task in done:
            try:
                await self._steam_run_task   
            except Exception as e:
                logger.exception(f"Unable to authenticate to steam backend: {repr(e)}")
                raise
            else:
                raise UnknownError("Unexcpeted, silent websocket close.")
        else:
            logger.warning(
                f"Failed to login on steam server within {USER_INFO_CACHE_INITIALIZED_TIMEOUT} seconds."
            )
            await self._cancel_task(self._steam_run_task)
            raise BackendTimeout()