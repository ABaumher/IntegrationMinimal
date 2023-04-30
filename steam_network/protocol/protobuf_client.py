import asyncio
import gzip
import hashlib
import ipaddress
import json
import logging
import socket
import struct
from itertools import count
from typing import Awaitable, Callable, Dict, Optional, Any
from typing import List, NamedTuple

import vdf

from .consts import EMsg, EResult, EAccountType, EFriendRelationship, EPersonaState
from .messages import steammessages_base_pb2, steammessages_clientserver_login_pb2, steammessages_auth_pb2, \
    steammessages_player_pb2, steammessages_clientserver_friends_pb2, steammessages_clientserver_pb2, \
    steammessages_chat_pb2, steammessages_clientserver_2_pb2, steammessages_clientserver_userstats_pb2, \
    steammessages_clientserver_appinfo_pb2, steammessages_webui_friends_pb2, service_cloudconfigstore_pb2, \
    enums_pb2
from .types import SteamId, ProtoUserInfo

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
LOG_SENSITIVE_DATA = False


class SteamLicense(NamedTuple):
    license: steammessages_clientserver_pb2.CMsgClientLicenseList.License  # type: ignore[name-defined]
    shared: bool


class ProtobufClient:
    _PROTO_MASK = 0x80000000
    _ACCOUNT_ID_MASK = 0x0110000100000000
    _IP_OBFUSCATION_MASK = 0x606573A4
    _MSG_PROTOCOL_VERSION = 65580
    _MSG_CLIENT_PACKAGE_VERSION = 1561159470

    def __init__(self, set_socket):
        self._socket = set_socket
        self.rsa_handler: Optional[Callable[[steammessages_auth_pb2.CAuthentication_GetPasswordRSAPublicKey_Response], Awaitable[None]]] = None
        self.log_on_handler: Optional[Callable[[steammessages_clientserver_login_pb2.CMsgClientLogonResponse], Awaitable[None]]] = None
        self.log_off_handler: Optional[Callable[[EResult], Awaitable[None]]] = None
        self.user_info_handler: Optional[Callable[[int, ProtoUserInfo], Awaitable[None]]] = None
        self.user_authentication_handler: Optional[Callable[[str, Any], Awaitable[None]]] = None
        self.steam_id: Optional[int] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._session_id: Optional[int] = None
        self._job_id_iterator = count(1)
        self.job_list = []

        self.account_info_retrieved = asyncio.Event()
        self.login_key_retrieved = asyncio.Event()
        self.collections = {'event': asyncio.Event(),
                            'collections': dict()}

    async def close(self, send_log_off):
        if send_log_off:
            await self.send_log_off_message()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()

    async def wait_closed(self):
        pass

    async def run(self):
        while True:
            for job in self.job_list.copy():
                logger.info(f"New job on list {job}")
            try:
                packet = await asyncio.wait_for(self._socket.recv(), 0.1)
                await self._process_packet(packet)
            except asyncio.TimeoutError:
                pass

    async def send_log_off_message(self):
        message = steammessages_clientserver_login_pb2.CMsgClientLogOff()
        logger.info("Sending log off message")
        try:
            await self._send(EMsg.ClientLogOff, message)
        except Exception as e:
            logger.error(f"Unable to send logoff message {repr(e)}")

    async def _send_service_method_with_name(self, message, target_job_name: str):
        emsg = EMsg.ServiceMethodCallFromClientNonAuthed if self.steam_id is None else EMsg.ServiceMethodCallFromClient;
        await self._send(emsg, message, target_job_name= target_job_name)

    #new workflow: get rsa public key -> log on with password -> handle steam guard -> confirm login
    #each is getting a dedicated function so i don't go insane.
    #confirm login is the old log_on_token call.


    #send the get rsa key request
    #imho we should just do a send and receive back to back instead of this bouncing around, but whatever. 
    async def get_rsa_public_key(self, account_name: str):
        message = steammessages_auth_pb2.CAuthentication_GetPasswordRSAPublicKey_Request()
        message.account_name = account_name
        await self._send_service_method_with_name(message, "Authentication.GetPasswordRSAPublicKey#1") #parsed from SteamKit's gobbledygook   

    #process the received the rsa key response. Because we will need all the information about this process, we send the entire message up the chain.
    async def _process_rsa(self, body):
        message = steammessages_auth_pb2.CAuthentication_GetPasswordRSAPublicKey_Response()
        message.ParseFromString(body)

        if (self.rsa_handler is not None):
            self.rsa_handler(message)

    #send our initial login request. It should succeed, but we won't get all the stuff we need. 
    async def log_on_password(self, account_name:str, enciphered_password:bytes, public_key_timestamp:int, os_value:int):
         #initialize the device details sub-message or whatever you want to call it.
        device_details = steammessages_auth_pb2.CAuthentication_DeviceDetails()
        device_details.device_friendly_name = socket.gethostname() + " (GOG Galaxy)"
        device_details.os_type = os_value if os_value >= 0 else 0

        message = steammessages_auth_pb2.CAuthentication_BeginAuthSessionViaCredentials_Request()
        message.account_name = account_name
        message.encrypted_password = enciphered_password
        message.website_id = "Client"
        message.device_friendly_name = socket.gethostname() + " (GOG Galaxy)"
        message.encryption_timestamp = public_key_timestamp
        message.platform_type = steammessages_auth_pb2.EAuthTokenPlatformType.k_EAuthTokenPlatformType_SteamClient #no idea if this line will work.
        #message.persistence = enums_pb2.ESessionPersistence.k_ESessionPersistence_Persistent # this is the default value and i have no idea how reflected enums work in python.
        message.device_details = device_details
        #message.guard_data = ""
        logger.info("Sending log on message using credentials in new authorization workflow")
        await self._send_service_method_with_name(message, "Authentication.BeginAuthSessionViaCredentials#1")

    async def _process_log_on_password(self, body):
        pass

    async def handle_steam_guard(self, code:str, code_type):
        pass

    async def _process_steam_guard(self, body):
        #message = 
        pass
    
    #send a message requesting a new access token using our refresh token. 
    async def refresh_access_token(self, refresh_token):
        pass

    #process the response and obtain our access token. 
    async def _process_refresh_access_token(self, body):
        pass
    


    async def log_on_token(self, account_name, token, used_server_cell_id, machine_id, os_value, sentry):
        message = await self._prepare_log_on_msg(account_name, machine_id, os_value, sentry)
        message.cell_id = used_server_cell_id
        message.login_key = token
        logger.info("Sending log on message using token")
        await self._send(EMsg.ClientLogon, message)

    async def _prepare_log_on_msg(self, account_name: str, machine_id: bytes, os_value: int, sentry) -> "steammessages_clientserver_login_pb2.CMsgClientLogon":
        message = steammessages_clientserver_login_pb2.CMsgClientLogon()
        message.account_name = account_name
        message.protocol_version = self._MSG_PROTOCOL_VERSION
        message.client_package_version = self._MSG_CLIENT_PACKAGE_VERSION
        message.client_language = "english"
        message.should_remember_password = True
        message.supports_rate_limit_response = True
        message.steamguard_dont_remember_computer = False
        message.obfuscated_private_ip.v4 = await self._get_obfuscated_private_ip()
        message.qos_level = 3
        message.machine_name = socket.gethostname()
        message.client_os_type = os_value if os_value >= 0 else 0
        message.machine_id = machine_id

        if sentry:
            logger.info("Sentry present")
            message.eresult_sentryfile = EResult.OK
            message.sha_sentryfile = sentry
        else:
            message.eresult_sentryfile = EResult.FileNotFound

        return message

    async def _get_obfuscated_private_ip(self) -> int:
        logger.info('Websocket state is: %s' % self._socket.state.name)
        await self._socket.ensure_open()
        host, port = self._socket.local_address
        ip = int(ipaddress.IPv4Address(host))
        obfuscated_ip = ip ^ self._IP_OBFUSCATION_MASK
        logger.debug(f"Local obfuscated IP: {obfuscated_ip}")
        return obfuscated_ip

    async def accept_update_machine_auth(self, jobid_target, sha_hash, offset, filename, cubtowrite):
        message = steammessages_clientserver_2_pb2.CMsgClientUpdateMachineAuthResponse()
        message.filename = filename
        message.eresult = EResult.OK
        message.sha_file = sha_hash
        message.getlasterror = 0
        message.offset = offset
        message.cubwrote = cubtowrite

        await self._send(EMsg.ClientUpdateMachineAuthResponse, message, None, jobid_target, None)

    async def _send(
        self,
        emsg,
        message,
        source_job_id=None,
        target_job_id=None,
        target_job_name=None
    ):
        proto_header = steammessages_base_pb2.CMsgProtoBufHeader()
        if self.steam_id is not None:
            proto_header.steamid = self.steam_id
        else:
            proto_header.steamid = 0 + self._ACCOUNT_ID_MASK
        if self._session_id is not None:
            proto_header.client_sessionid = self._session_id
        if source_job_id is not None:
            proto_header.jobid_source = source_job_id
        if target_job_id is not None:
            proto_header.jobid_target = target_job_id
        if target_job_name is not None:
            proto_header.target_job_name = target_job_name

        header = proto_header.SerializeToString()

        body = message.SerializeToString()
        data = struct.pack("<2I", emsg | self._PROTO_MASK, len(header))
        data = data + header + body

        if LOG_SENSITIVE_DATA:
            logger.info("[Out] %s (%dB), params:\n", repr(emsg), len(data), repr(message))
        else:
            logger.info("[Out] %s (%dB)", repr(emsg), len(data))
        await self._socket.send(data)

    async def _heartbeat(self, interval):
        message = steammessages_clientserver_login_pb2.CMsgClientHeartBeat()
        while True:
            await asyncio.sleep(interval)
            await self._send(EMsg.ClientHeartBeat, message)

    async def _process_packet(self, packet):
        package_size = len(packet)
        logger.debug("Processing packet of %d bytes", package_size)
        if package_size < 8:
            logger.warning("Package too small, ignoring...")
        raw_emsg = struct.unpack("<I", packet[:4])[0]
        emsg: int = raw_emsg & ~self._PROTO_MASK
        if raw_emsg & self._PROTO_MASK != 0:
            header_len = struct.unpack("<I", packet[4:8])[0]
            header = steammessages_base_pb2.CMsgProtoBufHeader()
            header.ParseFromString(packet[8:8 + header_len])
            if header.client_sessionid != 0:
                if self._session_id is None:
                    logger.info("New session id: %d", header.client_sessionid)
                    self._session_id = header.client_sessionid
                if self._session_id != header.client_sessionid:
                    logger.warning('Received session_id %s while client one is %s', header.client_sessionId, self._session_id)
            await self._process_message(emsg, header, packet[8 + header_len:])
        else:
            logger.warning("Packet for %d -> EMsg.%s with extended header - ignoring", emsg, EMsg(emsg).name)

    async def _process_message(self, emsg: int, header, body):
        logger.info("[In] %d -> EMsg.%s", emsg, EMsg(emsg).name)
        if emsg == EMsg.Multi:
            await self._process_multi(body)
        elif emsg == EMsg.ClientLogOnResponse:
            await self._process_client_log_on_response(body)
        elif emsg == EMsg.ClientLoggedOff:
            await self._process_client_logged_off(body)
        elif emsg == EMsg.ClientFriendsList:
            await self._process_client_friend_list(body)
        elif emsg == EMsg.ClientGetAppOwnershipTicketResponse:
            await self._process_client_get_app_ownership_ticket_response(body)
        elif emsg == EMsg.ClientPersonaState:
            await self._process_client_persona_state(body)
        elif emsg == EMsg.ClientLicenseList:
            await self._process_license_list(body)
        elif emsg == EMsg.PICSProductInfoResponse:
            await self._process_product_info_response(body)
        elif emsg == EMsg.ClientGetUserStatsResponse:
            await self._process_user_stats_response(body)
        elif emsg == EMsg.ClientAccountInfo:
            await self._process_account_info(body)
        elif emsg == EMsg.ClientNewLoginKey:
            await self._process_client_new_login_key(body, header.jobid_source)
        elif emsg == EMsg.ClientUpdateMachineAuth:
            await self._process_client_update_machine_auth(body, header.jobid_source)
        elif emsg == EMsg.ClientPlayerNicknameList:
            await self._process_user_nicknames(body)
        elif emsg == EMsg.ServiceMethod:
            await self._process_service_method_response(header.target_job_name, header.jobid_target, body)
        elif emsg == EMsg.ServiceMethodResponse:
            await self._process_service_method_response(header.target_job_name, header.jobid_target, body)
        else:
            logger.warning("Ignored message %d", emsg)

    async def _process_multi(self, body):
        logger.debug("Processing message Multi")
        message = steammessages_base_pb2.CMsgMulti()
        message.ParseFromString(body)
        if message.size_unzipped > 0:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, gzip.decompress, message.message_body)
        else:
            data = message.message_body

        data_size = len(data)
        offset = 0
        size_bytes = 4
        while offset + size_bytes <= data_size:
            size = struct.unpack("<I", data[offset:offset + size_bytes])[0]
            await self._process_packet(data[offset + size_bytes:offset + size_bytes + size])
            offset += size_bytes + size
        logger.debug("Finished processing message Multi")

    async def _process_client_get_app_ownership_ticket_response(self, body):
        logger.debug("Processing message ClientGetAppOwnershipTicketResponse")
        message = steammessages_clientserver_pb2.CMsgClientGetAppOwnershipTicketResponse()
        message.ParseFromString(body)
        result = message.eresult

        if result == EResult.OK:
            if self.app_ownership_ticket_handler is not None:
                await self.app_ownership_ticket_handler(message.app_id, message.ticket)
        else:
            logger.warning("ClientGetAppOwnershipTicketResponse result: %s", repr(result))

    #This is expected to always succeed in the new workflow. 
    async def _process_client_log_on_response(self, body):
        logger.debug("Processing message ClientLogOnResponse")
        message = steammessages_clientserver_login_pb2.CMsgClientLogonResponse()
        message.ParseFromString(body)
        
        if self.log_on_handler is not None:
            await self.log_on_handler(message)

    async def _process_client_update_machine_auth(self, body, jobid_source):
        logger.debug("Processing message ClientUpdateMachineAuth")
        message = steammessages_clientserver_2_pb2.CMsgClientUpdateMachineAuth()
        message.ParseFromString(body)

        sentry_sha = hashlib.sha1(message.bytes).digest()
        await self.user_authentication_handler('sentry', sentry_sha)
        await self.accept_update_machine_auth(jobid_source, sentry_sha, message.offset, message.filename, message.cubtowrite)

    async def _process_client_logged_off(self, body):
        logger.debug("Processing message ClientLoggedOff")
        message = steammessages_clientserver_login_pb2.CMsgClientLoggedOff()
        message.ParseFromString(body)
        result = message.eresult

        assert self._heartbeat_task is not None
        self._heartbeat_task.cancel()

        if self.log_off_handler is not None:
            await self.log_off_handler(result)

    async def _process_service_method_response(self, target_job_name, target_job_id, body):
        logger.info("Processing message ServiceMethodResponse %s", target_job_name)
        if target_job_name == 'Community.GetAppRichPresenceLocalization#1':
            await self._process_rich_presence_translations(body)
        elif target_job_name == 'Player.ClientGetLastPlayedTimes#1':
            await self._process_user_time_response(body)
        elif target_job_name == 'CloudConfigStore.Download#1':
            await self._process_collections_response(body)
        elif target_job_name == 'Authentication.GetPasswordRSAPublicKey#1':
            await self._process_rsa(body)
        else: 
            logger.warning("Service Method not expected. Likely needs to be processed, but isn't. Service Method Name: " + target_job_name)

