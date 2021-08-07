"""
    BAPSicle Server
    Next-gen audio playout server for University Radio York playout,
    based on WebStudio interface.

    Flask Server

    Authors:
        Matthew Stratford
        Michael Grace

    Date:
        October, November 2020
"""
from file_manager import FileManager
import multiprocessing
from multiprocessing.queues import Queue
import multiprocessing.managers as m
import threading
import queue
import time
from typing import Any, Optional
import json
from setproctitle import setproctitle
from helpers.os_environment import isBundelled, isMacOS

if not isMacOS():
    # Rip, this doesn't like threading on MacOS.
    import pyttsx3

if isBundelled():
    import build

import package
from typing import Dict, List
from helpers.state_manager import StateManager
from helpers.logging_manager import LoggingManager
from websocket_server import WebsocketServer
from web_server import WebServer
from channel_handler import ChannelHandler
from controllers.mattchbox_usb import MattchBox
from helpers.the_terminator import Terminator
from channel import Channel

PROCESS_KILL_TIMEOUT_S = 5

setproctitle("server.py")

""" Proxy Manager to proxy Class Objects into multiprocessing processes, instead of making a copy. """


class ProxyManager(m.BaseManager):
    pass  # Pass is really enough. Nothing needs to be done here.


class BAPSicleServer:

    default_state = {
        "server_version": "unknown",
        "server_build": "unknown",
        "server_branch": "unknown",
        "server_beta": True,
        "server_name": "URY BAPSicle",
        "host": "localhost",
        "port": 13500,
        "ws_port": 13501,
        "num_channels": 3,
        "serial_port": None,
        "ser_connected": False,
        "myradio_api_key": None,
        "myradio_base_url": "https://ury.org.uk/myradio",
        "myradio_api_url": "https://ury.org.uk/api",
        "myradio_api_tracklist_source": "",
        "running_state": "running",
        "tracklist_mode": "off",
    }

    channel_to_q: List[Queue] = []
    channel_from_q: List[Queue] = []
    ui_to_q: Queue
    websocket_to_q: Queue
    controller_to_q: Queue
    file_to_q: queue.Queue
    api_from_q: Queue
    api_to_q: Queue

    channel: List[multiprocessing.Process] = []
    websockets_server: Optional[threading.Thread] = None
    controller_handler: Optional[threading.Thread] = None
    channel_handler: Optional[threading.Thread] = None
    file_manager: Optional[threading.Thread] = None
    webserver: Optional[multiprocessing.Process] = None

    def __init__(self):

        while True:
            self.startServer()

            self.check_processes()

            self.stopServer()

            if self.state.get()["running_state"] == "restarting":
                continue

            break

    def check_processes(self):

        terminator = Terminator()
        log_function = self.logger.log.info

        while not terminator.terminate and self.state.get()["running_state"] == "running":

            for channel in range(self.state.get()["num_channels"]):
                if not self.channel[channel] or not self.channel[channel].is_alive():

                    try:
                        self.channel[channel].kill()
                    except:
                        pass


                    log_function("Channel {} not running, (re)starting.".format(channel))
                    self.channel[channel] = multiprocessing.Process(
                        target=Channel,
                        args=(channel, self.channel_to_q[channel], self.channel_from_q[channel], self.state)
                    )
                    if self.channel[channel]:
                        self.channel[channel].start()



            if not self.channel_handler or not self.channel_handler.is_alive():

                try:
                    self.channel_handler.kill()
                    del self.channel_handler
                except:
                    pass


                log_function("Channel Handler not running, (re)starting.")
                self.channel_handler = threading.Thread(
                    target=ChannelHandler,
                    args=(self.channel_from_q, self.websocket_to_q, self.ui_to_q, self.controller_to_q, self.file_to_q),
                )
                self.channel_handler.start()


            if not self.file_manager or not self.file_manager.is_alive():

                try:
                    self.file_manager.kill()
                    del self.file_manager
                except:
                    pass


                log_function("File Manager not running, (re)starting.")
                # Use len(player_to_q) for channel count.
                self.file_manager = threading.Thread(
                    target=FileManager,
                    args=(len(self.channel_to_q), self.file_to_q, self.state),
                )
                self.file_manager.start()

            if not self.websockets_server or not self.websockets_server.is_alive():

                try:
                    self.websockets_server.kill()
                    del self.websockets_server
                except:
                    pass


                log_function("Websocket Server not running, (re)starting.")
                self.websockets_server = threading.Thread(
                    target=WebsocketServer, args=(self.channel_to_q, self.websocket_to_q, self.state)
                )
                self.websockets_server.start()


            # Sanic has it's own asyncio handling, so give it it's own process.
            if not self.webserver or not self.webserver.is_alive():

                try:
                    self.webserver.kill()
                    del self.webserver
                except:
                    pass


                log_function("Webserver not running, (re)starting.")
                self.webserver = multiprocessing.Process(
                    target=WebServer, args=(self.channel_to_q, self.ui_to_q, self.state)
                )
                self.webserver.start()

            if not self.controller_handler or not self.controller_handler.is_alive():

                try:
                    self.controller_handler.kill()
                    del self.controller_handler
                except:
                    pass


                log_function("Controller Handler not running, (re)starting.")
                self.controller_handler = threading.Thread(
                    target=MattchBox, args=(self.channel_to_q, self.controller_to_q, self.state)
                )
                self.controller_handler.start()

            # After first starting processes, switch logger to error, since any future starts will have been failures.
            log_function = self.logger.log.error
            time.sleep(1)

    def startServer(self):
        #if isMacOS():
        #    multiprocessing.set_start_method("spawn", True)

        #process_title = "startServer"
        #setproctitle(process_title)
        #multiprocessing.current_process().name = process_title

        self.logger = LoggingManager("BAPSicleServer")

        # Since we're passing the StateManager across processes, it must be made a manager.
        # PLEASE NOTE: You can't read attributes directly, use state.get()["var"] and state.update("var", "val")
        ProxyManager.register("StateManager", StateManager)
        manager = ProxyManager()
        manager.start()
        self.state: StateManager = manager.StateManager("BAPSicleServer", self.logger, self.default_state)

        self.state.update("running_state", "running")

        print("Launching BAPSicle...")

        # TODO: Check these match, if not, trigger any upgrade noticies / welcome
        self.state.update("server_version", package.VERSION)
        self.state.update("server_build", package.BUILD)
        self.state.update("server_branch", package.BRANCH)
        self.state.update("server_beta", package.BETA)

        channel_count = self.state.get()["num_channels"]
        self.channel = [None] * channel_count

        self.ui_to_q=multiprocessing.Queue()
        self.controller_to_q = multiprocessing.Queue()
        self.file_to_q = queue.Queue()
        self.websocket_to_q = multiprocessing.Queue()

        for channel in range(self.state.get()["num_channels"]):

            self.channel_to_q.append(multiprocessing.Queue())
            self.channel_from_q.append(multiprocessing.Queue())

        print("Welcome to BAPSicle Server version: {}, build: {}.".format(package.VERSION, package.BUILD))
        print("The Server UI is available at http://{}:{}".format(self.state.get()["host"], self.state.get()["port"]))

        # TODO Move this to channel or installer.
        if False:
            if not isMacOS():

                # Temporary RIP.

                # Welcome Speech

                text_to_speach = pyttsx3.init()
                text_to_speach.save_to_file(
                    """Thank-you for installing BAPSicle - the play-out server from the broadcasting and presenting suite.
                By default, this server is accepting connections on port 13500
                The version of the server service is {}
                Please refer to the documentation included with this application for further assistance.""".format(
                        package.VERSION
                    ),
                    "dev/welcome.mp3",
                )
                text_to_speach.runAndWait()

                new_item: Dict[str, Any] = {
                    "channel_weight": 0,
                    "filename": "dev/welcome.mp3",
                    "title": "Welcome to BAPSicle",
                    "artist": "University Radio York",
                }

                self.channel_to_q[0].put("ADD:" + json.dumps(new_item))
                self.channel_to_q[0].put("LOAD:0")
                self.channel_to_q[0].put("PLAY")

    def stopServer(self):
        print("Stopping BASPicle Server.")

        print("Stopping Websocket Server")
        self.websocket_to_q.put("0:WEBSOCKET:QUIT")
        if self.websockets_server:
            self.websockets_server.join(timeout=PROCESS_KILL_TIMEOUT_S)
        del self.websockets_server

        print("Stopping Channels")
        for q in self.channel_to_q:
            q.put("ALL:QUIT")

        for channel in self.channel:
            channel.join(timeout=PROCESS_KILL_TIMEOUT_S)

        del self.channel

        print("Stopping Web Server")
        if self.webserver:
            self.webserver.terminate()
            self.webserver.join(timeout=PROCESS_KILL_TIMEOUT_S)
            del self.webserver

        print("Stopping Channel Handler")
        if self.channel_handler:
            #self.channel_handler.terminate()
            self.channel_handler.join(timeout=PROCESS_KILL_TIMEOUT_S)
            del self.channel_handler

        print("Stopping File Manager")
        if self.file_manager:
            #self.file_manager.terminate()
            self.file_manager.join(timeout=PROCESS_KILL_TIMEOUT_S)
            del self.file_manager

        print("Stopping Controllers")
        if self.controller_handler:
        #    self.controller_handler.terminate()
            self.controller_handler.join(timeout=PROCESS_KILL_TIMEOUT_S)
            del self.controller_handler
        print("Stopped all processes.")


if __name__ == "__main__":
    raise Exception("BAPSicle is a service. Please run it like one.")
